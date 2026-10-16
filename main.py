import calendar
import os
from datetime import date, datetime, timedelta

import fdb
from flask import (Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, session)
from fpdf import FPDF

app = Flask(__name__)

app.config["SECRET_KEY"] = "1234"
host = "localhost"
database = r"C:\Users\Aluno\Downloads\teste-movimentacoes-credmais-main\BANCO.FDB"
user = "SYSDBA"
password = "sysdba"


ID_USUARIO = 1

# Valores gravados na coluna TIPO da tabela MOV_FINANCEIRA
TIPO_RECEITA = 1
TIPO_DESPESA = 0

# chave do filtro (vem na URL) -> texto mostrado no botão e no PDF
PERIODOS = {
    "ultimos": "Últimos 3 Meses",
    "proximos": "Próximos 3 Meses",
    "todos": "Todo o Tempo",
}


def conectar():
    return fdb.connect(
        host=host,
        database=database,
        user=user,
        password=password
    )


def formatar_reais(valor):
    # O Python escreve 1234.5 como "1,234.50" (padrão americano).
    # No Brasil é "1.234,50", então precisamos trocar a vírgula e o ponto de lugar.
    # Usamos o "X" no meio para a troca não se misturar.
    texto = f"{valor:,.2f}"        # "1,234.50"
    texto = texto.replace(",", "X")  # "1X234.50"
    texto = texto.replace(".", ",")  # "1X234,50"
    texto = texto.replace("X", ".")  # "1.234,50"
    return texto


def datas_do_periodo(periodo):
    """Devolve a data de início e a data final do filtro escolhido."""
    hoje = date.today()

    if periodo == "ultimos":
        # de 90 dias atrás até hoje (3 meses)
        inicio = hoje - timedelta(days=90)
        fim = hoje
    elif periodo == "proximos":
        # de hoje até 90 dias para frente (pega as fixas dos meses seguintes)
        inicio = hoje
        fim = hoje + timedelta(days=90)
    else:
        # "todos": uma data bem antiga até uma data bem distante
        inicio = date(2000, 1, 1)
        fim = date(2100, 1, 1)

    return inicio, fim


# consultas do banco
def montar_movimentacao(linha):
    # linha: id, data, descricao, tipo, valor, classificacao
    if linha[3] == TIPO_RECEITA:
        categoria = "Receita"
        classe = "receita"
        sinal = "+"
    else:
        categoria = "Despesa"
        classe = "despesa"
        sinal = "-"

    if linha[5] == 1:
        classificacao = "Fixa"
    else:
        classificacao = "Variável"

    # se a descrição estiver vazia no banco (None), usa um texto vazio
    descricao = linha[2]
    if descricao is None:
        descricao = ""

    valor = float(linha[4])

    return {
        "id": linha[0],
        "data": linha[1].strftime("%d/%m"),
        "data_completa": linha[1].strftime("%d/%m/%Y"),
        "descricao": descricao,
        "categoria": categoria,
        "classe": classe,
        "sinal": sinal,
        "classificacao": classificacao,
        "valor": valor,
        "valor_texto": formatar_reais(valor)
    }


def buscar_movimentacoes(data_inicio, data_fim):
    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "SELECT ID_MOV_FINANCEIRA, DATA_LANCAMENTO, DESCRICAO, TIPO, VALOR, CLASSIFICACAO "
        "FROM MOV_FINANCEIRA "
        "WHERE ID_USUARIO = ? AND DATA_LANCAMENTO >= ? AND DATA_LANCAMENTO <= ? "
        "ORDER BY DATA_LANCAMENTO DESC, ID_MOV_FINANCEIRA DESC",
        (ID_USUARIO, data_inicio, data_fim)
    )
    linhas = cursor.fetchall()
    cursor.close()
    con.close()

    movimentacoes = []
    for linha in linhas:
        movimentacoes.append(montar_movimentacao(linha))
    return movimentacoes


def buscar_movimentacao(id_mov):
    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "SELECT ID_MOV_FINANCEIRA, DATA_LANCAMENTO, DESCRICAO, TIPO, VALOR, CLASSIFICACAO "
        "FROM MOV_FINANCEIRA "
        "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
        (id_mov, ID_USUARIO)
    )
    linha = cursor.fetchone()
    cursor.close()
    con.close()

    if linha is None:
        return None
    return montar_movimentacao(linha)


def somar(tipo, data_inicio=date(2000, 1, 1)):
    # sem data, soma tudo desde o ano 2000
    con = conectar()
    cursor = con.cursor()
    cursor.execute(
        "SELECT VALOR FROM MOV_FINANCEIRA "
        "WHERE ID_USUARIO = ? AND TIPO = ? AND DATA_LANCAMENTO >= ?",
        (ID_USUARIO, tipo, data_inicio)
    )
    linhas = cursor.fetchall()
    cursor.close()
    con.close()

    total = 0
    for linha in linhas:
        total += float(linha[0])
    return total


@app.route("/")
@app.route("/movimentacoes")
def inicio():
    # request.args pega o que vem na URL depois do "?" (ex: /?periodo=todos)
    periodo = request.args.get("periodo", "ultimos")
    if periodo not in PERIODOS:
        periodo = "ultimos"

    data_inicio, data_fim = datas_do_periodo(periodo)
    dados = buscar_movimentacoes(data_inicio, data_fim)

    # Saldo considera o historico do usuário
    saldo = somar(TIPO_RECEITA) - somar(TIPO_DESPESA)

    # Os cartões dizem "Nos últimos 30 dias"
    inicio_30_dias = date.today() - timedelta(days=30)
    receitas = somar(TIPO_RECEITA, inicio_30_dias)
    despesas = somar(TIPO_DESPESA, inicio_30_dias)

    return render_template(
        "index.html",
        dados=dados,
        saldo_texto=formatar_reais(saldo),
        receitas_texto=formatar_reais(receitas),
        despesas_texto=formatar_reais(despesas),
        periodo=periodo
    )


@app.route("/nova-movimentacao", methods=["GET", "POST"])
def nova_movimentacao():
    if request.method == "POST":
        tipo = request.form.get("tipo", "").strip()
        categoria = request.form.get("categoria", "").strip()
        valor = request.form.get("valor", "").strip()
        classificacao = request.form.get("classificacao", "2")
        meses = request.form.get("meses", "1")

        if not tipo:
            flash("Informe o tipo de movimentação.", "erro")
            return redirect(url_for("nova_movimentacao"))

        if categoria not in ("Receita", "Despesa"):
            flash("Selecione Receita ou Despesa.", "erro")
            return redirect(url_for("nova_movimentacao"))

        try:
            valor_numerico = float(valor.replace(",", "."))
        except ValueError:
            valor_numerico = 0

        if valor_numerico <= 0:
            flash("Insira um valor válido.", "erro")
            return redirect(url_for("nova_movimentacao"))

        # no banco a coluna CLASSIFICACAO so aceita 1 (fixa) ou 2 (variavel)
        if classificacao == "1":
            classificacao_numero = 1
            try:
                quantidade = int(meses)
            except ValueError:
                quantidade = 0
            if quantidade < 1 or quantidade > 120:
                flash("Informe de 1 a 120 meses.", "erro")
                return redirect(url_for("nova_movimentacao"))
        else:
            classificacao_numero = 2
            quantidade = 1  # variavel grava so uma vez

        tipo_numero = TIPO_RECEITA if categoria == "Receita" else TIPO_DESPESA

        con = conectar()
        cursor = con.cursor()
        for i in range(quantidade):
            if i == 0:
                data = date.today()
            else:
                # soma i meses na data de hoje
                total_meses = date.today().month - 1 + i
                ano = date.today().year + total_meses // 12
                mes = total_meses % 12 + 1
                ultimo_dia = calendar.monthrange(ano, mes)[1]  # ultimo dia do mes (28, 29, 30 ou 31)
                dia = min(date.today().day, ultimo_dia)  # mantem o dia, so diminui se o mes nao tiver esse dia (ex: 31 em fevereiro)
                data = date(ano, mes, dia)
            cursor.execute(
                "INSERT INTO MOV_FINANCEIRA "
                "(TIPO, VALOR, DATA_LANCAMENTO, DESCRICAO, ID_USUARIO, CLASSIFICACAO) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tipo_numero, valor_numerico, data, tipo, ID_USUARIO, classificacao_numero)
            )
        con.commit()  # commit depois do for: grava todos os meses ou nenhum
        cursor.close()
        con.close()

        # guarda os dados na session (memória do navegador do usuário)
        # para a tela de sucesso conseguir mostrar o que foi registrado
        if categoria == "Receita":
            classe = "receita"
        else:
            classe = "despesa"

        session["ultima_movimentacao"] = {
            "valor_texto": formatar_reais(valor_numerico),
            "categoria": categoria,
            "descricao": tipo,
            "classe": classe
        }
        return redirect(url_for("movimentacao_registrada"))

    return render_template("nova_movimentacao.html")


@app.route("/movimentacao-registrada")
def movimentacao_registrada():
    # pop pega os dados e já apaga da session
    # (se a pessoa abrir essa página sem ter registrado nada, volta para o início)
    dados = session.pop("ultima_movimentacao", None)

    if dados is None:
        return redirect(url_for("inicio"))

    return render_template("movimentacao_registrada.html", dados=dados)


@app.route("/movimentacao/<int:id_mov>")
def visualizar_movimentacao(id_mov):
    mov = buscar_movimentacao(id_mov)

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    return render_template("visualizar_movimentacao.html", mov=mov)


@app.route("/movimentacao/<int:id_mov>/editar", methods=["GET", "POST"])
def editar_movimentacao(id_mov):
    mov = buscar_movimentacao(id_mov)

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    if request.method == "POST":
        # Só a descrição pode ser alterada (valor, categoria e data ficam como estão)
        descricao = request.form.get("descricao", "").strip()

        if not descricao:
            flash("Informe a descrição da movimentação.", "erro")
            return redirect(url_for("editar_movimentacao", id_mov=id_mov))

        if len(descricao) > 100:
            flash("A descrição pode ter no máximo 100 caracteres.", "erro")
            return redirect(url_for("editar_movimentacao", id_mov=id_mov))

        con = conectar()
        cursor = con.cursor()
        cursor.execute(
            "UPDATE MOV_FINANCEIRA SET DESCRICAO = ? "
            "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
            (descricao, id_mov, ID_USUARIO)
        )
        con.commit()
        cursor.close()
        con.close()

        flash("Descrição atualizada com sucesso!", "sucesso")
        return redirect(url_for("visualizar_movimentacao", id_mov=id_mov))

    return render_template("editar_movimentacao.html", mov=mov)


@app.route("/movimentacao/<int:id_mov>/excluir", methods=["POST"])
def excluir_movimentacao(id_mov):
    # id_mov é o número que veio na URL (ex: /movimentacao/5/excluir).
    # Busca antes para ver se a movimentação existe e é do usuário.
    mov = buscar_movimentacao(id_mov)

    if mov is None:
        flash("Movimentação não encontrada.", "erro")
        return redirect(url_for("inicio"))

    con = conectar()
    cursor = con.cursor()

    if mov["classificacao"] == "Fixa":
        # Fixa: apaga ela e todas as outras "iguais".
        # Não existe uma coluna ligando as parcelas no banco, então "igual" é:
        # mesmo usuário, mesma categoria, mesma descrição e mesmo valor.
        if mov["categoria"] == "Receita":
            tipo_numero = TIPO_RECEITA
        else:
            tipo_numero = TIPO_DESPESA

        cursor.execute(
            "SELECT ID_MOV_FINANCEIRA, VALOR FROM MOV_FINANCEIRA "
            "WHERE ID_USUARIO = ? AND CLASSIFICACAO = 1 AND TIPO = ? AND DESCRICAO = ?",
            (ID_USUARIO, tipo_numero, mov["descricao"])
        )
        candidatas = cursor.fetchall()

        quantidade = 0
        for candidata in candidatas:
            # o valor é comparado aqui no Python (e não no SQL)
            # para não ter erro de casas decimais entre o banco e o float
            if float(candidata[1]) == mov["valor"]:
                cursor.execute(
                    "DELETE FROM MOV_FINANCEIRA "
                    "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
                    (candidata[0], ID_USUARIO)
                )
                quantidade += 1

        if quantidade == 1:
            mensagem = "Movimentação excluída com sucesso!"
        else:
            mensagem = f"{quantidade} movimentações fixas iguais foram excluídas com sucesso!"
    else:
        # Variável: apaga só ela mesma
        cursor.execute(
            "DELETE FROM MOV_FINANCEIRA "
            "WHERE ID_MOV_FINANCEIRA = ? AND ID_USUARIO = ?",
            (id_mov, ID_USUARIO)
        )
        mensagem = "Movimentação excluída com sucesso!"

    con.commit()  # commit só no final: apaga todas ou nenhuma
    cursor.close()
    con.close()

    flash(mensagem, "sucesso")
    return redirect(url_for("inicio"))


# ----------------------------------------------------------------
# RELATÓRIO EM PDF
# ----------------------------------------------------------------

def texto_pdf(texto):
    """O FPDF com fonte Arial só aceita Latin-1; troca o que não couber."""
    # Latin-1 é uma tabela de caracteres que tem os acentos do português.
    # Se aparecer algo que não existe nela (ex: emoji), vira "?" em vez de dar erro.
    texto = str(texto)
    texto = texto.encode("latin-1", "replace")
    texto = texto.decode("latin-1")
    return texto


@app.route("/relatorio", methods=["GET"])
def relatorio():
    # 1. Consulta: mesmo filtro que está selecionado na tela
    periodo = request.args.get("periodo", "ultimos")
    if periodo not in PERIODOS:
        periodo = "ultimos"

    data_inicio, data_fim = datas_do_periodo(periodo)
    movimentacoes = buscar_movimentacoes(data_inicio, data_fim)

    if not movimentacoes:
        # jsonify devolve a resposta em formato JSON (um texto organizado em chave: valor)
        return jsonify({"erro": "Nenhuma movimentação encontrada no período."}), 404

    # 2. Monta o PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(200, 10, texto_pdf("Relatório de Movimentações - CredMais"), ln=True, align="C")

    pdf.set_font("Arial", size=10)
    pdf.cell(200, 8, texto_pdf(f"Período: {PERIODOS[periodo]}  |  Gerado em: "
                               f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"),
             ln=True, align="C")

    # linha separadora
    pdf.ln(5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # cabeçalho da tabela
    pdf.set_font("Arial", style="B", size=11)
    pdf.cell(30, 10, "Data", border=1)
    pdf.cell(80, 10, texto_pdf("Descrição"), border=1)
    pdf.cell(35, 10, "Categoria", border=1)
    pdf.cell(45, 10, "Valor (R$)", border=1, ln=True)

    # linhas (uma por movimentação)
    pdf.set_font("Arial", size=11)
    total_receitas = 0
    total_despesas = 0

    for item in movimentacoes:
        if item["categoria"] == "Receita":
            total_receitas += item["valor"]
            sinal = "+"
        else:
            total_despesas += item["valor"]
            sinal = "-"

        pdf.cell(30, 10, item["data_completa"], border=1)
        pdf.cell(80, 10, texto_pdf(item["descricao"])[:40], border=1)
        pdf.cell(35, 10, item["categoria"], border=1)
        pdf.cell(45, 10, f"{sinal} {formatar_reais(item['valor'])}", border=1, ln=True)

    # totais no final
    contador = len(movimentacoes)
    pdf.ln(10)
    pdf.set_font("Arial", style="B", size=12)
    pdf.cell(200, 10, f"Total de movimentações: {contador}", ln=True, align="C")
    pdf.cell(200, 10, f"Receitas: R$ {formatar_reais(total_receitas)}", ln=True, align="C")
    pdf.cell(200, 10, f"Despesas: R$ {formatar_reais(total_despesas)}", ln=True, align="C")
    pdf.cell(200, 10, f"Saldo do período: R$ {formatar_reais(total_receitas - total_despesas)}",
             ln=True, align="C")

    # 3. Salva e envia para download
    pdf_path = os.path.join(app.root_path, "relatorio_movimentacoes.pdf")
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True, mimetype="application/pdf")


if __name__ == "__main__":
    app.run(debug=True)