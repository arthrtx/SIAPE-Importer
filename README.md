# SIAPE Importer

Tarefa de curso. Aluno: Arthur de Sal. Versão 1.5.

## O que é

É uma aplicação em Python que descarrega os ficheiros de servidores SIAPE do
[Portal da Transparência](https://portaldatransparencia.gov.br/download-de-dados/servidores)
e passa-os para uma base de dados MySQL.

## Para que serve

Todos os meses o Portal publica os dados dos servidores daquele mês. Fazer isso
à mão dá trabalho: baixar o ZIP, descompactar, arrumar os nomes das colunas e ir
inserindo no banco. Esta aplicação faz esse processo todo de uma vez, a partir do
período e dos dados do MySQL que se indiquem no formulário.

## Etapas

São quatro etapas, que podem ser executadas todas de uma vez ou uma a uma:

1. **Descarregar dados** — baixa um ZIP por mês;
2. **Descompactar ficheiros** — extrai os CSVs e apaga os ZIPs;
3. **Normalizar cabeçalhos** — limpa os nomes das colunas (tira acentos, espaços
   e símbolos como R$ e %) e detecta se o ficheiro é UTF-8 ou Latin-1;
4. **Enviar para MySQL** — cria as tabelas e insere os dados em lotes.

Os dados do MySQL (servidor, porta, utilizador, senha, base de dados e tabela)
só são pedidos na etapa 4. Para as restantes não é preciso preencher nada disso.

Cada tipo de ficheiro vai para a sua própria tabela, por exemplo
`servidores_cadastro` e `servidores_remuneracao`. Se o mesmo ficheiro for
importado outra vez, os registos antigos são apagados primeiro, portanto nunca
há duplicados. Se carregares em "Parar processo", o ficheiro que estava a ser
importado não fica com registos pela metade.

## Como rodar

Para usar a aplicação, descarrega o `Importador-SIAPE.exe` da página de
[Releases](https://github.com/arthrtx/Importador-SIAPE/releases) e dá duplo
clique. Não é preciso ter Python instalado.

Para correr a partir do código, dá duplo clique no `Abrir.bat` — ele instala o
que falta e abre o programa. Ou, à mão:

```bash
pip install -r requirements.txt
python main.py
```

## Estrutura

```text
Importador-SIAPE/
├── README.md              # este documento
├── main.py                # interface gráfica
├── pipeline.py            # download, extração, normalização e importação
├── requirements.txt       # dependências
└── Abrir.bat              # execução automática
```

O executável não está no repositório: está anexado na página de
[Releases](https://github.com/arthrtx/Importador-SIAPE/releases), onde se pode
descarregar o `Importador-SIAPE.exe` diretamente.

Os ficheiros ficam guardados numa pasta `dados_servidores_siape`, criada ao lado
da aplicação assim que se carrega num botão de execução.

## Origem do trabalho

Tarefa de curso. O professor forneceu o código inicial; eu organizei-o num
projeto só, corrigi os erros, fiz melhorias e criei a interface gráfica, que não
existia na versão original.