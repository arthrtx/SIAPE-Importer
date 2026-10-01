import csv
import json
import os
import re
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, fields

import pymysql

URL_ZIP = "https://portaldatransparencia.gov.br/download-de-dados/servidores/{}_Servidores_SIAPE"
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    "Referer": "https://portaldatransparencia.gov.br/download-de-dados/servidores",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
TAMANHO_LOTE = 500
TAMANHO_LOTE_BYTES = 2_000_000
COLUNAS_FIXAS = ("ARQUIVO_ORIGEM", "PERIODO_REFERENCIA", "TIPO_REGISTO")

PARAR = threading.Event()


class Paragem(Exception):
    pass


def parar():
    PARAR.set()


def reiniciar():
    PARAR.clear()


def verificar_paragem():
    if PARAR.is_set():
        raise Paragem()


def diretorio_aplicacao():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


@dataclass
class Configuracao:
    ano_inicial: int = 2026
    mes_inicial: int = 1
    ano_final: int = 2026
    mes_final: int = 6
    pasta_dados: str = ""
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""
    mysql_table: str = ""
    nome_servidor: str = ""

    def __post_init__(self):
        if not self.pasta_dados:
            self.pasta_dados = os.path.join(diretorio_aplicacao(), "dados_servidores_siape")

        if self.mysql_port in ("", None):
            self.mysql_port = 3306

    @property
    def ficheiro_inicial(self):
        return f"{self.ano_inicial}{self.mes_inicial:02d}"

    @property
    def ficheiro_final(self):
        return f"{self.ano_final}{self.mes_final:02d}"

    def validar(self, exigir_mysql=False):
        if not 2000 <= self.ano_inicial <= 2100 or not 2000 <= self.ano_final <= 2100:
            raise ValueError("Os anos devem estar entre 2000 e 2100.")
        if not 1 <= self.mes_inicial <= 12 or not 1 <= self.mes_final <= 12:
            raise ValueError("Os meses devem estar entre 1 e 12.")
        if (self.ano_inicial, self.mes_inicial) > (self.ano_final, self.mes_final):
            raise ValueError("O período inicial deve ser anterior ou igual ao final.")
        if not 1 <= int(self.mysql_port) <= 65535:
            raise ValueError("A porta deve estar entre 1 e 65535.")
        if exigir_mysql:
            if not self.mysql_host:
                raise ValueError("Preencha o servidor MySQL.")
            if not self.mysql_user:
                raise ValueError("Preencha o utilizador MySQL.")
            if not self.mysql_database:
                raise ValueError("Preencha a base de dados.")
            if not self.mysql_table:
                raise ValueError("Preencha o nome da tabela base.")
        os.makedirs(self.pasta_dados, exist_ok=True)

    def guardar(self):
        with open(os.path.join(diretorio_aplicacao(), "config_execucao.json"), "w", encoding="utf-8") as ficheiro:
            json.dump(asdict(self), ficheiro, indent=4, ensure_ascii=False)

    @classmethod
    def carregar(cls):
        caminho = os.path.join(diretorio_aplicacao(), "config_execucao.json")

        if not os.path.exists(caminho):
            return cls()

        with open(caminho, "r", encoding="utf-8") as ficheiro:
            dados = json.load(ficheiro)

        validos = {campo.name for campo in fields(cls)}
        return cls(**{chave: valor for chave, valor in dados.items() if chave in validos})


def periodos(config):
    ano, mes = config.ano_inicial, config.mes_inicial

    while (ano, mes) <= (config.ano_final, config.mes_final):
        yield f"{ano}{mes:02d}"
        mes += 1
        if mes > 12:
            mes, ano = 1, ano + 1


def ficheiros_do_intervalo(config, extensao):
    padrao = re.compile(rf"^(\d{{6}})(?:\d{{2}})?_.*\.{extensao}$", re.IGNORECASE)
    os.makedirs(config.pasta_dados, exist_ok=True)
    encontrados = []

    for nome in sorted(os.listdir(config.pasta_dados)):
        correspondencia = padrao.match(nome)

        if correspondencia and config.ficheiro_inicial <= correspondencia.group(1) <= config.ficheiro_final:
            encontrados.append(nome)

    return encontrados


def sem_acentos(texto):
    return unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("ASCII")


def codificacao(caminho, amostra=262144):
    try:
        tamanho = os.path.getsize(caminho)
        with open(caminho, "rb") as ficheiro:
            blocos = [ficheiro.read(amostra)]

            if tamanho > amostra * 3:
                ficheiro.seek(tamanho // 2)
                blocos.append(ficheiro.read(amostra))
                ficheiro.seek(max(0, tamanho - amostra))
                blocos.append(ficheiro.read(amostra))
    except OSError:
        return "latin1"

    for bloco in blocos:
        if bloco.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

    for bloco in blocos:
        try:
            bloco.decode("utf-8")
        except UnicodeDecodeError:
            return "latin1"

    return "utf-8"


def identificador(texto, prefixo="CAMPO", tamanho=64, maiusculas=True):
    texto = re.sub(r"[^A-Za-z0-9]+", "_", sem_acentos(texto.strip())).strip("_")
    texto = texto.upper() if maiusculas else texto

    if not texto:
        texto = prefixo

    if texto[0].isdigit():
        texto = f"{prefixo}_{texto}"

    return texto[:tamanho]


def tipo_do_ficheiro(nome):
    correspondencia = re.match(r"^\d{6}(?:\d{2})?_(.+)\.csv$", nome, re.IGNORECASE)
    return identificador(correspondencia.group(1) if correspondencia else "DESCONHECIDO", prefixo="TIPO")


def descarregar(config, log):
    os.makedirs(config.pasta_dados, exist_ok=True)
    sucesso, falhas = 0, 0

    for periodo in periodos(config):
        verificar_paragem()
        destino = os.path.join(config.pasta_dados, f"{periodo}_Servidores_SIAPE.zip")
        pedido = urllib.request.Request(URL_ZIP.format(periodo), headers=CABECALHOS)

        if os.path.exists(destino):
            os.remove(destino)

        try:
            with urllib.request.urlopen(pedido, timeout=300) as resposta, open(destino, "wb") as saida:
                while True:
                    verificar_paragem()
                    bloco = resposta.read(1048576)
                    if not bloco:
                        break
                    saida.write(bloco)

        except Paragem:
            if os.path.exists(destino):
                os.remove(destino)
            raise

        except urllib.error.HTTPError as erro:
            if os.path.exists(destino):
                os.remove(destino)
            log(f"[AVISO] {periodo}: dados indisponíveis (HTTP {erro.code})")
            falhas += 1

        except (urllib.error.URLError, OSError) as erro:
            if os.path.exists(destino):
                os.remove(destino)
            log(f"[AVISO] {periodo}: {getattr(erro, 'reason', erro)}")
            falhas += 1

        else:
            if os.path.getsize(destino) > 0:
                sucesso += 1
                log(f"[OK] {periodo}: {os.path.getsize(destino) / 1048576:.2f} MB")
            else:
                os.remove(destino)
                log(f"[AVISO] {periodo}: ficheiro ainda não publicado")
                falhas += 1

    log(f"Download concluído: {sucesso} descarregado(s), {falhas} indisponível(is).")


def descompactar(config, log):
    zips = ficheiros_do_intervalo(config, "zip")

    if not zips:
        log("Nenhum ficheiro ZIP encontrado no intervalo indicado.")
        return

    extraidos = 0

    for nome in zips:
        verificar_paragem()
        caminho = os.path.join(config.pasta_dados, nome)

        try:
            with zipfile.ZipFile(caminho) as ficheiro:
                conteudo = ficheiro.namelist()

                for membro in conteudo:
                    alvo = os.path.normpath(os.path.join(config.pasta_dados, membro))

                    if not alvo.startswith(os.path.abspath(config.pasta_dados) + os.sep) and os.path.abspath(alvo) != os.path.abspath(config.pasta_dados):
                        raise ValueError(f"entrada inválida no ZIP: {membro}")

                ficheiro.extractall(config.pasta_dados)

            os.remove(caminho)
            extraidos += len(conteudo)
            log(f"[OK] {nome}: {len(conteudo)} ficheiro(s) extraído(s)")

        except Paragem:
            raise

        except Exception as erro:
            log(f"[ERRO] {nome}: {erro}")

    log(f"Descompactação concluída: {extraidos} ficheiro(s).")


def nome_de_coluna(nome, indice):
    texto = nome.strip()

    for original, novo in (("US$", "USD"), ("U$", "USD"), ("R$", "BRL"), ("%", "PERCENTUAL")):
        texto = texto.replace(original, novo)

    return identificador(texto, prefixo=f"COLUNA_{indice + 1}")


def normalizar_cabecalho(cabecalho):
    resultado, repeticoes = [], {}

    for indice, nome in enumerate(cabecalho):
        base = nome_de_coluna(nome, indice)
        contador = repeticoes.get(base, 0) + 1
        repeticoes[base] = contador

        if contador == 1:
            resultado.append(base)
        else:
            sufixo = f"_{contador}"
            resultado.append(f"{base[:64 - len(sufixo)]}{sufixo}")

    return resultado


def normalizar(config, log):
    csvs = ficheiros_do_intervalo(config, "csv")

    if not csvs:
        log("Nenhum CSV encontrado no intervalo indicado.")
        return

    processados = 0

    for nome in csvs:
        verificar_paragem()
        caminho = os.path.join(config.pasta_dados, nome)
        temporario = f"{caminho}.tmp"

        try:
            leitura = codificacao(caminho)
            escrita = "utf-8" if leitura.startswith("utf-8") else leitura

            with open(caminho, "r", encoding=leitura, errors="replace", newline="") as entrada, open(
                temporario, "w", encoding=escrita, errors="replace", newline=""
            ) as saida:
                leitor = csv.reader(entrada, delimiter=";")
                escritor = csv.writer(saida, delimiter=";", lineterminator="\n")
                cabecalho = next(leitor, None)

                if cabecalho is None:
                    log(f"[AVISO] {nome}: ficheiro vazio")
                else:
                    novo_cabecalho = normalizar_cabecalho(cabecalho)
                    escritor.writerow(novo_cabecalho)

                    for contador, linha in enumerate(leitor, start=1):
                        escritor.writerow(linha)

                        if contador % 5000 == 0:
                            verificar_paragem()

            if cabecalho is None:
                os.remove(temporario)
                continue

            os.replace(temporario, caminho)
            processados += 1
            log(f"[OK] {nome}: {len(novo_cabecalho)} coluna(s)")

        except Paragem:
            if os.path.exists(temporario):
                os.remove(temporario)
            raise

        except Exception as erro:
            if os.path.exists(temporario):
                os.remove(temporario)
            log(f"[ERRO] {nome}: {erro}")

    log(f"Normalização concluída: {processados} ficheiro(s).")


ERROS_MYSQL = {
    1044: "o utilizador não tem permissão para criar a base de dados",
    1045: "utilizador ou palavra-passe inválidos",
    1049: "base de dados desconhecida",
    1061: "nome da base de dados inválido",
    1064: "erro de sintaxe SQL (nome de tabela ou coluna inválido)",
    1146: "a tabela não existe",
    2002: "ligação recusada pelo servidor",
    2003: "não foi possível ligar ao servidor (ligação recusada ou servidor indisponível)",
    2005: "endereço do servidor desconhecido",
    2013: "a ligação foi perdida durante a importação",
}


def explicar_erro(erro):
    codigo = erro.args[0] if getattr(erro, "args", None) else None

    if codigo in ERROS_MYSQL:
        return f"{ERROS_MYSQL[codigo]} (código {codigo})"

    return str(erro)


def garantir_base_dados(cursor, base_dados):
    nome = identificador(base_dados, prefixo="BASE", maiusculas=False)

    try:
        cursor.execute(f"USE `{nome}`")
        return nome
    except pymysql.err.OperationalError as erro:
        if erro.args[0] != 1049:
            raise

    cursor.execute(f"CREATE DATABASE `{nome}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cursor.execute(f"USE `{nome}`")
    return nome


def garantir_tabela(cursor, tabela, colunas):
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS `{tabela}` (
            `ID_CARGA` BIGINT NOT NULL AUTO_INCREMENT,
            `ARQUIVO_ORIGEM` VARCHAR(255) NOT NULL,
            `PERIODO_REFERENCIA` CHAR(6) NOT NULL,
            `TIPO_REGISTO` VARCHAR(100) NOT NULL,
            `DATA_IMPORTACAO` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`ID_CARGA`),
            INDEX `IDX_ARQUIVO_ORIGEM` (`ARQUIVO_ORIGEM`),
            INDEX `IDX_PERIODO_REFERENCIA` (`PERIODO_REFERENCIA`)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"""
    )

    cursor.execute(f"SHOW COLUMNS FROM `{tabela}`")
    existentes = {linha[0] for linha in cursor.fetchall()}

    for coluna in colunas:
        if coluna not in existentes:
            cursor.execute(f"ALTER TABLE `{tabela}` ADD COLUMN `{coluna}` LONGTEXT NULL")
            existentes.add(coluna)


def inserir(cursor, ligacao, tabela, colunas, lote):
    if not lote:
        return

    campos = list(COLUNAS_FIXAS) + list(colunas)
    sql = (
        f"INSERT INTO `{tabela}` ({', '.join(f'`{c}`' for c in campos)}) "
        f"VALUES ({', '.join(['%s'] * len(campos))})"
    )

    cursor.executemany(sql, lote)
    ligacao.commit()


def importar_ficheiro(cursor, ligacao, config, nome, log=lambda texto: None):
    caminho = os.path.join(config.pasta_dados, nome)
    tipo = tipo_do_ficheiro(nome)
    tabela = f"{identificador(config.mysql_table, prefixo='TABELA', tamanho=40)}_{tipo}"[:64]

    with open(caminho, "r", encoding=codificacao(caminho), errors="replace", newline="") as ficheiro:
        leitor = csv.reader(ficheiro, delimiter=";")
        cabecalho = next(leitor, None)

        if cabecalho is None:
            return 0

        campos = normalizar_cabecalho(cabecalho)
        garantir_tabela(cursor, tabela, campos)
        cursor.execute(f"DELETE FROM `{tabela}` WHERE `ARQUIVO_ORIGEM` = %s", (nome,))
        ligacao.commit()

        indice_nome = campos.index("NOME") if "NOME" in campos else None
        filtro = config.nome_servidor.strip().upper()
        periodo = re.match(r"^\d{6}", nome).group(0)

        if filtro and indice_nome is None:
            log(f"[AVISO] {nome}: não tem coluna NOME, o filtro por servidor foi ignorado")

        lote, registos, bytes_lote = [], 0, 0

        try:
            for linha in leitor:
                linha = [(valor.strip() or None) for valor in linha[: len(cabecalho)]]
                linha += [None] * (len(cabecalho) - len(linha))

                if filtro and indice_nome is not None and filtro not in (linha[indice_nome] or "").upper():
                    continue

                lote.append((nome, periodo, tipo, *linha))
                bytes_lote += sum(len(valor or "") for valor in linha)

                if len(lote) >= TAMANHO_LOTE or bytes_lote >= TAMANHO_LOTE_BYTES:
                    verificar_paragem()
                    inserir(cursor, ligacao, tabela, campos, lote)
                    registos += len(lote)
                    lote.clear()
                    bytes_lote = 0

            if lote:
                verificar_paragem()
                inserir(cursor, ligacao, tabela, campos, lote)
                registos += len(lote)

        except Paragem:
            ligacao.rollback()
            lote.clear()
            cursor.execute(f"DELETE FROM `{tabela}` WHERE `ARQUIVO_ORIGEM` = %s", (nome,))
            ligacao.commit()
            raise

    return registos


def importar(config, log):
    csvs = ficheiros_do_intervalo(config, "csv")

    if not csvs:
        log("Nenhum CSV encontrado no intervalo indicado.")
        return

    log(f"A ligar a {config.mysql_host}:{config.mysql_port}")

    try:
        ligacao = pymysql.connect(
            host=config.mysql_host,
            port=int(config.mysql_port),
            user=config.mysql_user,
            password=config.mysql_password,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=30,
            read_timeout=600,
        )
    except pymysql.err.MySQLError as erro:
        raise RuntimeError(f"ligação ao MySQL falhou: {explicar_erro(erro)}") from erro

    ficheiros, total = 0, 0

    try:
        with ligacao.cursor() as cursor:
            log(f"Base de dados: {garantir_base_dados(cursor, config.mysql_database)}")

            for nome in csvs:
                verificar_paragem()

                try:
                    registos = importar_ficheiro(cursor, ligacao, config, nome, log)
                    ficheiros += 1
                    total += registos
                    log(f"[OK] {nome}: {registos} registo(s)")

                except Paragem:
                    ligacao.rollback()
                    log(f"[AVISO] {nome}: importação interrompida, os registos deste ficheiro não foram guardados")
                    raise

                except Exception as erro:
                    ligacao.rollback()
                    log(f"[ERRO] {nome}: {erro}")
    finally:
        ligacao.close()

    log(f"Importação concluída: {ficheiros} ficheiro(s), {total} registo(s).")


ETAPAS = (
    ("download", "Descarregar dados", descarregar),
    ("extracao", "Descompactar ficheiros", descompactar),
    ("normalizacao", "Normalizar cabeçalhos", normalizar),
    ("mysql", "Enviar para MySQL", importar),
)


def executar(codigo, config, log):
    config.validar(exigir_mysql=codigo == "mysql")
    rotulo, funcao = next((rotulo, funcao) for identificador, rotulo, funcao in ETAPAS if identificador == codigo)
    log("")
    log(f"== {rotulo} ==")
    funcao(config, log)
    log(f"== {rotulo}: fim ==")


def executar_tudo(config, log):
    config.validar(exigir_mysql=True)
    for codigo, _, _ in ETAPAS:
        executar(codigo, config, log)
