
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    KeepTogether
)


# =========================================================
# 1. KONFIGURASI
# =========================================================

st.set_page_config(
    page_title="Surat Jalan - OXAR GLOBAL",
    page_icon="📄",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent

MASTER_PDF = BASE_DIR / "Data Harga - Google Spreadsheet.pdf"
LOGO_FILE = BASE_DIR / "logo_oxar.jpg"


# =========================================================
# 2. CSS DAN DESAIN APLIKASI
# =========================================================

st.markdown("""
<style>

.stApp {
    background-color: #f4f6fa;
    color: #172b42;
}

.block-container {
    max-width: 1180px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

.hero {
    background: linear-gradient(
        120deg,
        #10243a,
        #1d4260,
        #287a78
    );
    color: white;
    padding: 28px 30px;
    border-radius: 16px;
    margin-bottom: 22px;
}

.hero h1 {
    color: white !important;
    font-size: 29px;
    font-weight: 800;
    margin-bottom: 7px;
}

.hero p {
    color: #e5eef3 !important;
    margin: 0;
    font-size: 14px;
}

.section-title {
    font-size: 19px;
    font-weight: 800;
    color: #172b42;
    margin: 23px 0 12px;
}

.hint {
    background: #e4f3f0;
    border-left: 5px solid #16817c;
    padding: 14px 16px;
    border-radius: 9px;
    color: #174b48;
    margin-bottom: 14px;
    font-size: 14px;
}

div[data-testid="stMetric"] {
    background: #ffffff !important;
    border: 1px solid #d5deea !important;
    border-radius: 12px !important;
    padding: 16px !important;
    box-shadow: 0 2px 7px rgba(0,0,0,0.05);
}

div[data-testid="stMetricLabel"] {
    color: #475569 !important;
    font-weight: 700 !important;
}

div[data-testid="stMetricValue"] {
    color: #10243a !important;
    font-weight: 850 !important;
    font-size: 25px !important;
}

div[data-baseweb="input"] input {
    color: #172b42 !important;
}

div[data-baseweb="textarea"] textarea {
    color: #172b42 !important;
}

.stButton > button[kind="primary"] {
    background-color: #176b66;
    color: white;
    border-radius: 9px;
    font-weight: 700;
    border: none;
    min-height: 45px;
}

.stButton > button[kind="primary"]:hover {
    background-color: #10534f;
    color: white;
}

[data-testid="stDataFrame"] {
    background: white;
    border-radius: 10px;
}

div[data-testid="stAlert"] {
    border-radius: 9px;
}

</style>

<div class="hero">
    <h1>📄 SURAT JALAN OXAR GLOBAL</h1>
    <p>
        Sistem pembuatan Surat Jalan otomatis.
        Upload PDF, masukkan satu diskon untuk seluruh produk,
        lalu download hasilnya.
    </p>
</div>
""", unsafe_allow_html=True)


# =========================================================
# 3. FORMAT ANGKA
# =========================================================

def digits_only(value):
    return re.sub(r"[^0-9]", "", str(value))


def parse_price(value):
    digits = digits_only(value)
    return int(digits) if digits else 0


def rupiah(value):
    return "Rp" + f"{int(round(float(value))):,}".replace(",", ".")


def format_number(value):
    return f"{int(round(float(value))):,}".replace(",", ".")


def format_total(value):
    return (
        f"{float(value):,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def format_percent(value):
    return f"{float(value):.2f}".replace(".", ",") + "%"


def escape_html(value):
    value = str(value or "-")

    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# =========================================================
# 4. DATABASE MASTER SKU
# =========================================================

@st.cache_data(show_spinner=False)
def load_master_database(master_bytes):

    database = {}

    with pdfplumber.open(BytesIO(master_bytes)) as pdf:

        for page in pdf.pages:

            text = page.extract_text() or ""

            for line in text.splitlines():

                tokens = line.split()

                sku_position = next(
                    (
                        i for i, token in enumerate(tokens)
                        if re.fullmatch(r"\d{8,14}", token)
                    ),
                    None
                )

                if sku_position is None:
                    continue

                if sku_position < 2:
                    continue

                if sku_position + 1 >= len(tokens):
                    continue

                sku = tokens[sku_position]

                nama_produk = " ".join(
                    tokens[2:sku_position]
                ).strip()

                harga = parse_price(
                    tokens[sku_position + 1]
                )

                if sku and harga > 0:

                    database[sku] = {
                        "sku": sku,
                        "nama_produk": nama_produk,
                        "harga": harga
                    }

    return database


# =========================================================
# 5. MEMBACA HEADER PDF SURAT JALAN
# =========================================================

def extract_header(pdf_bytes):

    result = {
        "dari": "",
        "tujuan": "",
        "no_transfer": "",
        "tanggal": "",
        "catatan": ""
    }

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:

        text = "\n".join(
            page.extract_text() or ""
            for page in pdf.pages
        )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # DARI dan No Transfer
    match = re.search(
        r"DARI\s*:\s*(.*?)\s+No\.?\s*Transfer\s+([A-Z0-9\-]+)",
        text,
        re.IGNORECASE
    )

    if match:
        result["dari"] = match.group(1).strip()
        result["no_transfer"] = match.group(2).strip()

    # TANGGAL
    match = re.search(
        r"Tanggal\s+(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        result["tanggal"] = match.group(1).strip()

    # TUJUAN
    tujuan_parts = []
    tujuan_started = False

    for line in lines:

        if re.search(r"TUJUAN\s*:", line, re.IGNORECASE):

            tujuan_started = True

            bagian = re.split(
                r"TUJUAN\s*:",
                line,
                maxsplit=1,
                flags=re.IGNORECASE
            )[1]

            bagian = re.sub(
                r"\s+Tanggal\s+\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}.*$",
                "",
                bagian,
                flags=re.IGNORECASE
            )

            if bagian.strip():
                tujuan_parts.append(bagian.strip())

            continue

        if tujuan_started:

            if re.search(r"\bNO\s+SKU\b", line, re.IGNORECASE):
                break

            if re.match(
                r"^(DARI|No\.?\s*Transfer|Tanggal)\b",
                line,
                re.IGNORECASE
            ):
                continue

            tujuan_parts.append(line.strip())

    result["tujuan"] = " ".join(tujuan_parts).strip()

    # CATATAN
    match = re.search(
        r"Catatan\s*:\s*(.*?)(?=\n\s*Dicetak\s+tanggal|\Z)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:

        result["catatan"] = " ".join(
            line.strip()
            for line in match.group(1).splitlines()
            if line.strip()
        )

    return result


# =========================================================
# 6. MEMBACA SKU DAN QTY
# =========================================================

def extract_sku_qty(pdf_bytes):

    items = []
    errors = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:

        for page_number, page in enumerate(pdf.pages, start=1):

            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=2
            )

            sku_words = [
                word for word in words
                if re.fullmatch(r"\d{8,14}", word["text"])
            ]

            for sku_word in sku_words:

                sku = sku_word["text"]
                sku_y = sku_word["top"]

                qty_candidates = [
                    word for word in words
                    if 395 <= word["x0"] <= 425
                    and abs(word["top"] - sku_y) <= 3
                    and re.fullmatch(r"\d{1,5}", word["text"])
                ]

                if not qty_candidates:

                    errors.append(
                        f"QTY tidak ditemukan untuk SKU {sku} "
                        f"di halaman {page_number}."
                    )

                    continue

                qty_word = min(
                    qty_candidates,
                    key=lambda word: abs(word["top"] - sku_y)
                )

                qty = int(qty_word["text"])

                if qty > 0:

                    items.append({
                        "sku": sku,
                        "qty": qty
                    })

    # Gabungkan SKU yang sama
    combined = {}

    for item in items:

        sku = item["sku"]

        combined[sku] = (
            combined.get(sku, 0) + item["qty"]
        )

    rows = [
        {"sku": sku, "qty": qty}
        for sku, qty in combined.items()
    ]

    return rows, errors


# =========================================================
# 7. MEMBUAT PDF SURAT JALAN
# =========================================================

def build_pdf(df, header, diskon):

    output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=9 * mm,
        bottomMargin=12 * mm,
        title="Surat Jalan OXAR GLOBAL",
        author="OXAR GLOBAL"
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="SmallCustom",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="TitleCustom",
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=24,
        alignment=TA_RIGHT,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="MetadataRight",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        alignment=TA_LEFT,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="ProductCustom",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="HeaderCustom",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="SignatureHead",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.black
    ))

    styles.add(ParagraphStyle(
        name="SignatureLine",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        textColor=colors.black
    ))

    story = []

    # -----------------------------------------------------
    # LOGO DAN JUDUL
    # -----------------------------------------------------

    if LOGO_FILE.exists():

        logo = RLImage(
            str(LOGO_FILE),
            width=39 * mm,
            height=15 * mm
        )

        logo.hAlign = "LEFT"

    else:

        logo = Paragraph(
            "<b>OXAR GLOBAL</b>",
            styles["SmallCustom"]
        )

    right_header = Table(
        [
            [Paragraph("SURAT JALAN", styles["TitleCustom"])]
        ],
        colWidths=[88 * mm]
    )

    right_header.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)
    ]))

    header_table = Table(
        [[logo, right_header]],
        colWidths=[92 * mm, 88 * mm],
        rowHeights=[18 * mm]
    )

    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)
    ]))

    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------
    # DARI / TUJUAN DAN NO. TRANSFER / TANGGAL
    # KEDUANYA SEJAJAR
    # -----------------------------------------------------

    lokasi_asal = (header.get("dari") or "").strip()

    dari_text = (
        f"OXAR {lokasi_asal}"
        if lokasi_asal
        else "OXAR"
    )

    left_info = Table(
        [
            [
                Paragraph(
                    f"<b>DARI:</b> {escape_html(dari_text)}",
                    styles["SmallCustom"]
                )
            ],
            [
                Paragraph(
                    f"<b>TUJUAN:</b> {escape_html(header.get('tujuan') or '-')}",
                    styles["SmallCustom"]
                )
            ]
        ],
        colWidths=[92 * mm]
    )

    left_info.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3)
    ]))

    right_info = Table(
        [
            [
                Paragraph(
                    f"<b>No. Transfer:</b> {escape_html(header.get('no_transfer') or '-')}",
                    styles["MetadataRight"]
                )
            ],
            [
                Paragraph(
                    f"<b>Tanggal:</b> {escape_html(header.get('tanggal') or '-')}",
                    styles["MetadataRight"]
                )
            ]
        ],
        colWidths=[88 * mm]
    )

    right_info.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3)
    ]))

    info_row = Table(
        [[left_info, right_info]],
        colWidths=[92 * mm, 88 * mm]
    )

    info_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)
    ]))

    story.append(info_row)
    story.append(Spacer(1, 9 * mm))

    # -----------------------------------------------------
    # TABEL PRODUK
    # -----------------------------------------------------

    table_data = [[
        Paragraph("NO", styles["HeaderCustom"]),
        Paragraph("SKU", styles["HeaderCustom"]),
        Paragraph("NAMA BARANG", styles["HeaderCustom"]),
        Paragraph("QTY", styles["HeaderCustom"]),
        Paragraph("HARGA (UNIT)", styles["HeaderCustom"]),
        Paragraph("DISKON", styles["HeaderCustom"]),
        Paragraph("HARGA SETELAH<br/>DISKON", styles["HeaderCustom"])
    ]]

    subtotal = 0
    total_diskon = 0
    total_qty = 0

    for index, row in df.reset_index(drop=True).iterrows():

        sku = str(row["SKU"])
        nama = str(row["NAMA BARANG"])
        qty = int(row["QTY"])
        harga = int(row["HARGA (UNIT)"])

        nilai_subtotal = qty * harga
        nilai_diskon = nilai_subtotal * float(diskon) / 100
        harga_setelah_diskon = nilai_subtotal - nilai_diskon

        subtotal += nilai_subtotal
        total_diskon += nilai_diskon
        total_qty += qty

        table_data.append([
            str(index + 1),
            sku,
            Paragraph(
                escape_html(nama),
                styles["ProductCustom"]
            ),
            format_number(qty),
            rupiah(harga),
            format_percent(diskon),
            rupiah(harga_setelah_diskon)
        ])

    column_widths = [
        8 * mm,
        30 * mm,
        61 * mm,
        11 * mm,
        25 * mm,
        18 * mm,
        29 * mm
    ]

    product_table = Table(
        table_data,
        colWidths=column_widths,
        repeatRows=1
    )

    product_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F3F5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("ALIGN", (5, 1), (5, -1), "CENTER"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4)
    ]))

    story.append(product_table)

    # -----------------------------------------------------
    # TOTAL QTY DI BAWAH KOLOM QTY
    # -----------------------------------------------------

    qty_summary = Table(
        [[
            "",
            "Total Qty",
            "",
            format_number(total_qty),
            "",
            "",
            ""
        ]],
        colWidths=column_widths
    )

    qty_summary.setStyle(TableStyle([
        ("SPAN", (1, 0), (2, 0)),
        ("ALIGN", (1, 0), (2, 0), "RIGHT"),
        ("ALIGN", (3, 0), (3, 0), "CENTER"),
        ("FONTNAME", (1, 0), (3, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3)
    ]))

    story.append(qty_summary)
    story.append(Spacer(1, 3 * mm))

    # -----------------------------------------------------
    # RINGKASAN PERHITUNGAN
    # -----------------------------------------------------

    grand_total = subtotal - total_diskon

    summary_data = [
        ["", "", "", "", "Sub Total", rupiah(subtotal)],
        ["", "", "", "", "Diskon", rupiah(total_diskon)],
        ["", "", "", "", "Diskon Lainnya", rupiah(0)],
        ["", "", "", "", "Grand Total", rupiah(grand_total)]
    ]

    summary_widths = [
        8 * mm,
        30 * mm,
        61 * mm,
        11 * mm,
        36 * mm,
        36 * mm
    ]

    summary_table = Table(
        summary_data,
        colWidths=summary_widths
    )

    summary_table.setStyle(TableStyle([
        ("SPAN", (0, 0), (3, -1)),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (4, 3), (5, 3), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (4, 3), (5, 3), 0.8, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2)
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 5 * mm))

    # -----------------------------------------------------
    # CATATAN
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "<b>Catatan:</b>",
            styles["SmallCustom"]
        )
    )

    story.append(
        Paragraph(
            escape_html(header.get("catatan") or "-"),
            styles["SmallCustom"]
        )
    )

    # -----------------------------------------------------
    # TIGA TANDA TANGAN
    # DITEMPATKAN DI BAWAH CATATAN
    # DAN DI ATAS TANGGAL CETAK
    # -----------------------------------------------------

    story.append(Spacer(1, 18 * mm))

    signature_data = [
        [
            Paragraph("Diterima Oleh,", styles["SignatureHead"]),
            Paragraph("Dikirim Oleh,", styles["SignatureHead"]),
            Paragraph("Hormat Kami,", styles["SignatureHead"])
        ],
        ["", "", ""],
        [
            Paragraph(
                "( ........................................ )",
                styles["SignatureLine"]
            ),
            Paragraph(
                "( ........................................ )",
                styles["SignatureLine"]
            ),
            Paragraph(
                "( ........................................ )",
                styles["SignatureLine"]
            )
        ]
    ]

    signature_table = Table(
        signature_data,
        colWidths=[60 * mm, 60 * mm, 60 * mm],
        rowHeights=[7 * mm, 13 * mm, 7 * mm]
    )

    signature_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)
    ]))

    story.append(
        KeepTogether([signature_table])
    )

    # -----------------------------------------------------
    # TANGGAL CETAK PALING BAWAH
    # -----------------------------------------------------

    def draw_print_date(canvas, document):

        canvas.saveState()

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#333333"))

        canvas.drawString(
            13 * mm,
            9 * mm,
            "Dicetak tanggal : " +
            datetime.now().strftime("%d %b %Y %H:%M")
        )

        canvas.restoreState()

    doc.build(
        story,
        onFirstPage=draw_print_date,
        onLaterPages=draw_print_date
    )

    output.seek(0)

    return output.getvalue()


# =========================================================
# 8. MEMUAT DATABASE
# =========================================================

if not MASTER_PDF.exists():

    st.error(
        "Database harga tidak ditemukan. "
        "Pastikan Data Harga - Google Spreadsheet.pdf "
        "berada di repository GitHub."
    )

    st.stop()


master_db = load_master_database(
    MASTER_PDF.read_bytes()
)

if not master_db:

    st.error("Database SKU tidak berhasil dibaca.")

    st.stop()


st.success(
    f"Database harga aktif: {len(master_db):,} SKU."
)


# =========================================================
# 9. UPLOAD SURAT JALAN
# =========================================================

st.markdown(
    '<div class="section-title">1. Upload Surat Jalan</div>',
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader(
    "Pilih file PDF Surat Jalan",
    type=["pdf"],
    help="Upload PDF Surat Jalan asli."
)


if uploaded_file:

    pdf_bytes = uploaded_file.getvalue()

    header = extract_header(pdf_bytes)

    items, errors = extract_sku_qty(pdf_bytes)

    for error in errors:
        st.warning(error)

    if not items:

        st.error(
            "SKU dan QTY tidak berhasil dibaca dari PDF."
        )

        st.stop()

    # CEK SKU MASTER
    missing_skus = [
        item["sku"]
        for item in items
        if item["sku"] not in master_db
    ]

    if missing_skus:

        st.error(
            "SKU berikut tidak ditemukan di database harga:"
        )

        st.code("\n".join(missing_skus))

        st.stop()

    # =====================================================
    # INFORMASI SURAT JALAN
    # =====================================================

    st.markdown(
        '<div class="section-title">2. Informasi Surat Jalan</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)

    with col1:

        st.text_input(
            "DARI",
            value=header["dari"] or "Tidak terbaca",
            disabled=True
        )

        st.text_area(
            "TUJUAN",
            value=header["tujuan"] or "Tidak terbaca",
            disabled=True,
            height=80
        )

    with col2:

        st.text_input(
            "No. Transfer",
            value=header["no_transfer"] or "Tidak terbaca",
            disabled=True
        )

        st.text_input(
            "Tanggal",
            value=header["tanggal"] or "Tidak terbaca",
            disabled=True
        )

        st.text_area(
            "Catatan",
            value=header["catatan"] or "-",
            disabled=True,
            height=60
        )

    # =====================================================
    # SATU INPUT DISKON
    # =====================================================

    st.markdown(
        '<div class="section-title">3. Pengaturan Diskon</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="hint">
            <b>Diskon berlaku untuk seluruh produk.</b><br>
            Tim area cukup memasukkan persentase diskon satu kali.
            Sistem akan otomatis menerapkan diskon yang sama
            ke semua SKU dalam satu Surat Jalan.
        </div>
        """,
        unsafe_allow_html=True
    )

    diskon = st.number_input(
        "Masukkan Diskon Seluruh Produk (%)",
        min_value=0.0,
        max_value=100.0,
        value=20.0,
        step=1.0,
        format="%.2f",
        help="Contoh: masukkan 30 untuk diskon 30%."
    )

    st.info(
        f"Diskon aktif untuk semua produk: {format_percent(diskon)}"
    )

    # =====================================================
    # DATA PRODUK
    # =====================================================

    product_data = []

    for item in items:

        product = master_db[item["sku"]]

        product_data.append({
            "SKU": item["sku"],
            "NAMA BARANG": product["nama_produk"],
            "QTY": item["qty"],
            "HARGA (UNIT)": product["harga"],
            "DISKON (%)": diskon
        })

    df = pd.DataFrame(product_data)

    # =====================================================
    # PREVIEW PERHITUNGAN
    # =====================================================

    st.markdown(
        '<div class="section-title">4. Preview Produk dan Perhitungan</div>',
        unsafe_allow_html=True
    )

    preview = df.copy()

    preview["SUBTOTAL"] = (
        preview["QTY"] * preview["HARGA (UNIT)"]
    )

    preview["NILAI DISKON"] = (
        preview["SUBTOTAL"] * diskon / 100
    )

    preview["HARGA SETELAH DISKON"] = (
        preview["SUBTOTAL"] - preview["NILAI DISKON"]
    )

    display_df = preview.copy()

    display_df["HARGA (UNIT)"] = (
        display_df["HARGA (UNIT)"].map(rupiah)
    )

    display_df["DISKON (%)"] = (
        display_df["DISKON (%)"].map(format_percent)
    )

    display_df["SUBTOTAL"] = (
        display_df["SUBTOTAL"].map(rupiah)
    )

    display_df["NILAI DISKON"] = (
        display_df["NILAI DISKON"].map(rupiah)
    )

    display_df["HARGA SETELAH DISKON"] = (
        display_df["HARGA SETELAH DISKON"].map(rupiah)
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # =====================================================
    # RINGKASAN METRIC
    # =====================================================

    total_qty = int(preview["QTY"].sum())

    subtotal = float(
        preview["SUBTOTAL"].sum()
    )

    total_diskon = float(
        preview["NILAI DISKON"].sum()
    )

    grand_total = subtotal - total_diskon

    st.markdown(
        '<div class="section-title">5. Ringkasan Perhitungan</div>',
        unsafe_allow_html=True
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total Qty",
        format_number(total_qty)
    )

    col2.metric(
        "Sub Total",
        rupiah(subtotal)
    )

    col3.metric(
        "Total Diskon",
        rupiah(total_diskon)
    )

    col4.metric(
        "Grand Total",
        rupiah(grand_total)
    )

    # =====================================================
    # GENERATE PDF
    # =====================================================

    st.markdown(
        '<div class="section-title">6. Generate PDF Surat Jalan</div>',
        unsafe_allow_html=True
    )

    if st.button(
        "GENERATE PDF SURAT JALAN",
        type="primary",
        use_container_width=True
    ):

        if not header["dari"]:

            st.error(
                "Informasi DARI tidak terbaca dari PDF."
            )

        elif not header["tujuan"]:

            st.error(
                "Informasi TUJUAN tidak terbaca dari PDF."
            )

        else:

            pdf_output = build_pdf(
                df,
                header,
                diskon
            )

            nomor_file = re.sub(
                r"[^A-Za-z0-9_-]",
                "-",
                header["no_transfer"] or "hasil"
            )

            st.session_state["pdf_surat_jalan"] = pdf_output

            st.session_state["nama_file"] = (
                f"Surat_Jalan_{nomor_file}.pdf"
            )

            st.success(
                "PDF SURAT JALAN berhasil dibuat!"
            )

    # =====================================================
    # DOWNLOAD PDF
    # =====================================================

    if "pdf_surat_jalan" in st.session_state:

        st.download_button(
            label="DOWNLOAD PDF SURAT JALAN",
            data=st.session_state["pdf_surat_jalan"],
            file_name=st.session_state["nama_file"],
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )

else:

    st.info(
        "Silakan upload PDF Surat Jalan. "
        "Sistem akan membaca informasi, SKU, dan QTY secara otomatis."
    )


st.markdown("---")

st.caption(
    "OXAR GLOBAL | Sistem Pembuatan Surat Jalan"
)
