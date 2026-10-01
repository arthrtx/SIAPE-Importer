import os
import queue
import sys
import threading

import customtkinter as ctk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline
from pipeline import Configuracao, ETAPAS

ROTULOS = {identificador: rotulo for identificador, rotulo, _ in ETAPAS}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

DESTAQUE = "#2563EB"
TEXTO_CLARO = "#64748B"
PARAR_COR = "#DC2626"

FORMULARIO = (
    ("sec", "Período", ""),
    ("ano_inicial", "Ano inicial", "ex.: 2026"),
    ("mes_inicial", "Mês inicial", "de 1 a 12"),
    ("ano_final", "Ano final", "ex.: 2026"),
    ("mes_final", "Mês final", "de 1 a 12"),
    ("sec", "Ligação MySQL", ""),
    ("mysql_host", "Servidor", "ex.: mysql.exemplo.com"),
    ("mysql_port", "Porta", "ex.: 3306"),
    ("mysql_user", "Utilizador", "utilizador da base de dados"),
    ("mysql_password", "Palavra-passe", "palavra-passe"),
    ("mysql_database", "Base de dados", "nome da base de dados"),
    ("mysql_table", "Tabela base", "ex.: servidores"),
    ("sec", "Filtro", ""),
    ("nome_servidor", "Nome do servidor", "vazio = todos"),
)


class Aplicacao(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Importador SIAPE")
        self.geometry("1000x660")
        self.minsize(880, 580)
        self.configure(fg_color="#EEF2F7")

        self.campos = {}
        self.fila = queue.Queue()
        self.em_execucao = False

        self.construir()
        self.preencher(Configuracao.carregar())
        self.after(80, self.drenar_fila)

    def construir(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        cabecalho = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=0, height=72)
        cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew")
        cabecalho.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cabecalho, text="Importador SIAPE", font=ctk.CTkFont(size=22, weight="bold"), text_color="#0F172A"
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(14, 0))

        ctk.CTkLabel(
            cabecalho,
            text="Portal da Transparência · Servidores · MySQL     |     Arthur de Sal · versão 1.5",
            font=ctk.CTkFont(size=12),
            text_color=TEXTO_CLARO,
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))

        self.construir_formulario()
        self.construir_registo()

        ctk.CTkLabel(
            self,
            text="Os ficheiros ficam na pasta dados_servidores_siape",
            font=ctk.CTkFont(size=11),
            text_color=TEXTO_CLARO,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 10))

    def construir_formulario(self):
        painel = ctk.CTkScrollableFrame(
            self,
            width=330,
            fg_color="#F8FAFC",
            corner_radius=0,
            label_text="Configuração",
            label_anchor="w",
            label_fg_color="#F8FAFC",
            label_text_color="#0F172A",
            label_font=ctk.CTkFont(size=14, weight="bold"),
        )
        painel.grid(row=1, column=0, sticky="nsw", padx=(12, 6), pady=12)
        painel.grid_columnconfigure(1, weight=1)

        linha = 0

        for chave, rotulo, dica in FORMULARIO:
            if chave == "sec":
                ctk.CTkLabel(
                    painel,
                    text=rotulo.upper(),
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=DESTAQUE,
                    anchor="w",
                ).grid(row=linha, column=0, columnspan=2, sticky="w", pady=(16, 4))
                linha += 1
                continue

            ctk.CTkLabel(
                painel, text=rotulo, font=ctk.CTkFont(size=12), text_color="#334155", anchor="w"
            ).grid(row=linha, column=0, columnspan=2, sticky="w")

            entrada = ctk.CTkEntry(
                painel,
                height=32,
                corner_radius=8,
                placeholder_text=dica,
                placeholder_text_color="#94A3B8",
                show="*" if chave == "mysql_password" else "",
            )
            entrada.grid(row=linha + 1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
            self.campos[chave] = entrada
            linha += 2

        botao_tudo = ctk.CTkButton(
            painel,
            text="Executar tudo",
            height=42,
            corner_radius=10,
            fg_color=DESTAQUE,
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.iniciar(None),
        )
        botao_tudo.grid(row=linha, column=0, columnspan=2, sticky="ew", pady=(18, 6))
        linha += 1

        self.botao_parar = ctk.CTkButton(
            painel,
            text="Parar processo",
            height=36,
            corner_radius=10,
            fg_color=PARAR_COR,
            hover_color="#B91C1C",
            state="disabled",
            command=self.parar,
        )
        self.botao_parar.grid(row=linha, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        linha += 1

        self.botoes = {"tudo": botao_tudo}

        for indice, (identificador, rotulo, _) in enumerate(ETAPAS):
            botao = ctk.CTkButton(
                painel,
                text=rotulo,
                height=34,
                corner_radius=10,
                fg_color="#FFFFFF",
                hover_color="#E2E8F0",
                text_color="#1E293B",
                border_width=1,
                border_color="#CBD5E1",
                anchor="w",
                command=lambda etapa=identificador: self.iniciar(etapa),
            )
            botao.grid(row=linha + indice // 2, column=indice % 2, sticky="ew", padx=(0, 4) if indice % 2 == 0 else (4, 0), pady=3)
            self.botoes[identificador] = botao

    def construir_registo(self):
        painel = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=14)
        painel.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=12)
        painel.grid_rowconfigure(1, weight=1)
        painel.grid_columnconfigure(0, weight=1)

        topo = ctk.CTkFrame(painel, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        topo.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topo, text="Registo da execução", font=ctk.CTkFont(size=14, weight="bold"), text_color="#0F172A"
        ).grid(row=0, column=0, sticky="w")

        self.estado = ctk.CTkLabel(topo, text="Pronto", font=ctk.CTkFont(size=12), text_color=TEXTO_CLARO)
        self.estado.grid(row=0, column=1, sticky="e")

        self.caixa = ctk.CTkTextbox(
            painel,
            corner_radius=10,
            fg_color="#0F172A",
            text_color="#E2E8F0",
            font=ctk.CTkFont(family="Consolas", size=12),
            state="disabled",
        )
        self.caixa.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))

        self.barra = ctk.CTkProgressBar(painel, height=6, corner_radius=3, fg_color="#E2E8F0", progress_color=DESTAQUE)
        self.barra.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.barra.set(0)

    def preencher(self, config):
        valores = {
            "ano_inicial": config.ano_inicial,
            "mes_inicial": config.mes_inicial,
            "ano_final": config.ano_final,
            "mes_final": config.mes_final,
            "nome_servidor": config.nome_servidor,
            **{chave: getattr(config, chave) for chave in self.campos if chave.startswith("mysql_")},
        }

        for chave, valor in valores.items():
            if str(valor) == "":
                continue

            self.campos[chave].delete(0, "end")
            self.campos[chave].insert(0, str(valor))

    def ler_inteiro(self, chave, rotulo):
        try:
            return int(self.campos[chave].get().strip())
        except ValueError:
            raise ValueError(f"{rotulo}: introduza um número inteiro válido.")

    def ler_configuracao(self):
        return Configuracao(
            ano_inicial=self.ler_inteiro("ano_inicial", "Ano inicial"),
            mes_inicial=self.ler_inteiro("mes_inicial", "Mês inicial"),
            ano_final=self.ler_inteiro("ano_final", "Ano final"),
            mes_final=self.ler_inteiro("mes_final", "Mês final"),
            nome_servidor=self.campos["nome_servidor"].get().strip(),
            **{
                chave: self.ler_inteiro(chave, rotulo) if chave == "mysql_port" else self.campos[chave].get()
                for chave, rotulo, _ in FORMULARIO
                if chave.startswith("mysql_")
            },
        )

    def iniciar(self, identificador):
        if self.em_execucao:
            return

        try:
            config = self.ler_configuracao()
            config.validar(exigir_mysql=identificador in (None, "mysql"))
            config.guardar()
        except (ValueError, OSError) as erro:
            messagebox.showwarning("Configuração inválida", str(erro), parent=self)
            return

        self.em_execucao = True
        pipeline.reiniciar()
        self.mudar_estado(True)
        rotulo = "Execução completa" if identificador is None else ROTULOS[identificador]
        self.registar(f"Etapa iniciada: {rotulo}.")

        threading.Thread(target=self.correr, args=(identificador, config), daemon=True).start()

    def parar(self):
        if not self.em_execucao:
            return

        pipeline.parar()
        self.estado.configure(text="A parar...", text_color=PARAR_COR)
        self.registar("Paragem pedida, a aguardar o fim da operação atual...")

    def correr(self, identificador, config):
        try:
            if identificador is None:
                pipeline.executar_tudo(config, self.registar)
            else:
                pipeline.executar(identificador, config, self.registar)
            self.fila.put(lambda: self.finalizar("Concluído com sucesso."))

        except pipeline.Paragem:
            self.fila.put(lambda: self.finalizar("Processo parado pelo utilizador."))

        except Exception as erro:
            mensagem = f"Falhou: {erro}"
            self.registar(f"[ERRO] {erro}")
            self.fila.put(lambda: self.finalizar(mensagem))

    def mudar_estado(self, a_correr):
        for botao in self.botoes.values():
            botao.configure(state="disabled" if a_correr else "normal")

        self.botao_parar.configure(state="normal" if a_correr else "disabled")

        if a_correr:
            self.barra.configure(mode="indeterminate")
            self.barra.start()
            self.estado.configure(text="A processar...", text_color=DESTAQUE)
        else:
            self.barra.stop()
            self.barra.configure(mode="determinate")
            self.barra.set(0)

    def finalizar(self, mensagem):
        self.em_execucao = False
        self.mudar_estado(False)
        self.estado.configure(text=mensagem, text_color=TEXTO_CLARO)
        self.registar(mensagem)

    def registar(self, texto):
        self.fila.put(texto)

    def anexar(self, texto):
        self.caixa.configure(state="normal")
        self.caixa.insert("end", f"{texto}\n")
        self.caixa.see("end")
        self.caixa.configure(state="disabled")

    def drenar_fila(self):
        try:
            while True:
                item = self.fila.get_nowait()
                try:
                    item() if callable(item) else self.anexar(item)
                except Exception as erro:
                    self.caixa.configure(state="normal")
                    self.caixa.insert("end", f"[ERRO na interface] {erro}\n")
                    self.caixa.configure(state="disabled")
        except queue.Empty:
            pass

        self.after(80, self.drenar_fila)


if __name__ == "__main__":
    Aplicacao().mainloop()
