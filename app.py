import re
from io import BytesIO
from pathlib import Path
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage
)

# =========================================================
# KONFIGURASI
# =========================================================
st.set_page_config(page_title="Surat Jalan ke Pesanan", page_icon="📄", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
MASTER_PDF = BASE_DIR / "Data Harga - Google Spreadsheet.pdf"
LOGO_FILE = BASE_DIR / "logo_oxar.jpg"


# =========================================================
# FORMAT
# =========================================================
def only_digits(v):
    return re.sub(r"[^0-9]", "", str(v))

def parse_price(v):
    d = only_digits(v)
    return int(d) if d else 0

def rupiah(v):
    return "Rp" + f"{int(round(float(v))):,}".replace(",", ".")

def format_percent(v):
    return f"{float(v):.2f}".replace(".", ",") + "%"

def format_id_number(v):
    return f"{int(round(float(v))):,}".replace(",", ".")

def format_total(v):
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =========================================================
# DATABASE MASTER
# =========================================================
@st.cache_data(show_spinner=False)
def load_master_database(master_bytes):
    db = {}

    with pdfplumber.open(BytesIO(master_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                tokens = line.split()
                sku_pos = next(
                    (i for i, tok in enumerate(tokens) if re.fullmatch(r"\d{8,14}", tok)),
                    None
                )

                if sku_pos is None or sku_pos < 2 or sku_pos + 1 >= len(tokens):
                    continue

                sku = tokens[sku_pos].strip()
                nama = " ".join(tokens[2:sku_pos]).strip()
                harga = parse_price(tokens[sku_pos + 1])

                if sku and nama and harga > 0:
                    db[sku] = {
                        "sku": sku,
                        "nama_produk": nama,
                        "harga": harga
                    }

    return db


# =========================================================
# BACA HEADER SURAT JALAN
# =========================================================
def extract_delivery_header(pdf_bytes):
    info = {
        "dari": "",
        "tujuan": "",
        "no_transfer": "",
        "tanggal": "",
        "catatan": ""
    }

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            return info

        text = pdf.pages[0].extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Ambil No Transfer
        m = re.search(r"No\.\s*Transfer\s+([A-Z0-9\-]+)", text, re.I)
        if m:
            info["no_transfer"] = m.group(1).strip()

        # Ambil tanggal
        m = re.search(r"Tanggal\s+([0-9]{1,2}\s+[A-Za-z]{3}\s+[0-9]{4})", text, re.I)
        if m:
            info["tanggal"] = m.group(1).strip()

        # Ambil DARI
        for i, line in enumerate(lines):
            if line.upper().startswith("DARI"):
                # contoh: DARI : Banjarmasin
                parts = line.split(":")
                if len(parts) > 1:
                    info["dari"] = parts[1].strip()
                elif i + 1 < len(lines):
                    info["dari"] = lines[i + 1].strip()

        # Ambil TUJUAN
        for i, line in enumerate(lines):
            if line.upper().startswith("TUJUAN"):
                parts = line.split(":")
                tujuan_lines = []

                if len(parts) > 1 and parts[1].strip():
                    tujuan_lines.append(parts[1].strip())

                # ambil beberapa baris sesudahnya sampai sebelum header tabel
                j = i + 1
                while j < len(lines):
                    t = lines[j]
                    if (
                        "NO SKU" in t.upper()
                        or "TOTAL QTY" in t.upper()
                        or t.upper().startswith("CATATAN")
                    ):
                        break
                    if not any(x in t.upper() for x in ["NO. TRANSFER", "TANGGAL"]):
                        tujuan_lines.append(t.strip())
                    j += 1

                tujuan_lines = [x for x in tujuan_lines if x]
                info["tujuan"] = " ".join(tujuan_lines).strip()
                break

        # Ambil catatan
        for i, line in enumerate(lines):
            if line.upper().startswith("CATATAN"):
                if i + 1 < len(lines):
                    info["catatan"] = lines[i + 1].strip()
                break

    return info


# =========================================================
# BACA SKU + QTY DARI SURAT JALAN
# =========================================================
def extract_sku_qty(pdf_bytes):
    items = []
    errors = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=2, y_tolerance=2)

            sku_words = [
                w for w in words
                if re.fullmatch(r"\d{8,14}", w["text"])
            ]

            for sku_word in sku_words:
                sku = sku_word["text"]
                y = sku_word["top"]

                qty_candidates = [
                    w for w in words
                    if 390 <= w["x0"] <= 440
                    and abs(w["top"] - y) <= 3
                    and re.fullmatch(r"\d+", w["text"])
                ]

                if not qty_candidates:
                    errors.append(f"QTY tidak ditemukan untuk SKU {sku} di halaman {page_no}")
                    continue

                qty_word = sorted(qty_candidates, key=lambda w: (abs(w["top"] - y), w["x0"]))[0]
                qty = int(qty_word["text"])
                items.append({"sku": sku, "qty": qty})

    # gabungkan SKU sama
    combined = {}
    for item in items:
        combined[item["sku"]] = combined.get(item["sku"], 0) + item["qty"]

    rows = [{"sku": sku, "qty": qty} for sku, qty in combined.items()]
    return rows, errors


# =========================================================
# BUAT PDF PESANAN
# =========================================================
def build_pdf(df, header_info):
    out = BytesIO()

    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=12*mm,
        rightMargin=12*mm,
        topMargin=10*mm,
        bottomMargin=10*mm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontName="Helvetica", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="Item", fontName="Helvetica", fontSize=7, leading=8))
    styles.add(ParagraphStyle(name="TitleRight", fontName="Helvetica-Bold", fontSize=20, alignment=TA_RIGHT))

    story = []

    # Header
    logo = RLImage(str(LOGO_FILE), width=38*mm, height=14*mm) if LOGO_FILE.exists() else Paragraph("OXAR GLOBAL", styles["SmallBold"])

    header_table = Table(
        [[logo, Paragraph("PESANAN", styles["TitleRight"])]],
        colWidths=[95*mm, 85*mm]
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8*mm))

    tujuan = header_info.get("tujuan", "")
    dari = header_info.get("dari", "")
    no_transfer = header_info.get("no_transfer", "")
    tanggal = header_info.get("tanggal", "")
    catatan = header_info.get("catatan", "")

    left_block = [
        Paragraph(f"<b>Kepada:</b> {tujuan}", styles["SmallBold"]),
        Paragraph(dari, styles["Small"]),
        Spacer(1, 4*mm),
        Paragraph(f"<b>{tujuan}</b>", styles["SmallBold"]),
        Paragraph(dari, styles["Small"]),
    ]

    right_block = [
        Paragraph(f"<b>No Pesanan</b> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; {no_transfer}", styles["SmallBold"]),
        Paragraph(f"<b>Tanggal</b> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; {tanggal}", styles["SmallBold"]),
        Paragraph(f"<b>No. Ref.</b>", styles["SmallBold"]),
    ]

    info_table = Table([[left_block, right_block]], colWidths=[115*mm, 65*mm])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 15*mm))

    # Tabel item
    table_data = [[
        "NO", "SKU", "NAMA BARANG", "QTY", "HARGA (UNIT)", "DISKON", "HARGA SETELAH\nDISKON"
    ]]

    subtotal = 0
    total_diskon = 0
    total_qty = 0

    for idx, row in df.iterrows():
        qty = int(row["QTY"])
        harga = int(row["HARGA (UNIT)"])
        diskon_pct = float(row["DISKON (%)"])

        row_subtotal = qty * harga
        row_diskon = row_subtotal * diskon_pct / 100
        row_net = row_subtotal - row_diskon

        subtotal += row_subtotal
        total_diskon += row_diskon
        total_qty += qty

        table_data.append([
            str(idx + 1),
            row["SKU"],
            Paragraph(str(row["NAMA BARANG"]), styles["Item"]),
            str(qty),
            rupiah(harga),
            format_percent(diskon_pct),
            rupiah(row_net)
        ])

    col_widths = [8*mm, 30*mm, 62*mm, 10*mm, 24*mm, 18*mm, 30*mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (3, 1), (5, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)

    # Ringkasan
    diskon_lainnya = 0
    grand_total = subtotal - total_diskon - diskon_lainnya

    summary_data = [
        ["Total Qty", str(total_qty), "Sub Total", format_total(subtotal)],
        ["", "", "Diskon", format_total(total_diskon)],
        ["", "", "Diskon Lainnya", format_total(diskon_lainnya)],
        ["", "", "Grand Total", format_total(grand_total)],
    ]

    summary_table = Table(summary_data, colWidths=[28*mm, 18*mm, 88*mm, 46*mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (2, 3), (3, 3), "Helvetica-Bold"),
        ("LINEABOVE", (2, 3), (3, 3), 0.8, colors.black),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 7*mm))

    story.append(Paragraph("<b>Catatan :</b>", styles["SmallBold"]))
    story.append(Paragraph(catatan, styles["Small"]))
    story.append(Spacer(1, 35*mm))

    sign_table = Table(
        [
            ["Diterima Oleh,", "Dikirim Oleh,", "Hormat Kami,"],
            ["", "", ""],
            ["( ............................................... )",
             "( ............................................... )",
             "( ............................................... )"]
        ],
        colWidths=[60*mm, 60*mm, 60*mm]
    )
    sign_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(sign_table)
    story.append(Spacer(1, 7*mm))
    story.append(Paragraph(
        f"Dicetak tanggal :             {datetime.now().strftime('%d %b %Y %H:%M')}",
        styles["Small"]
    ))

    doc.build(story)
    out.seek(0)
    return out.getvalue()


# =========================================================
# APP
# =========================================================
st.title("📄 Surat Jalan → Pesanan")
st.caption("Upload Surat Jalan, isi diskon per SKU, lalu download PDF PESANAN.")

if not MASTER_PDF.exists():
    st.error("File database harga tidak ditemukan.")
    st.stop()

master_db = load_master_database(MASTER_PDF.read_bytes())
st.success(f"Database master aktif: {len(master_db)} SKU.")

uploaded = st.file_uploader("Upload PDF Surat Jalan", type=["pdf"])

if uploaded:
    pdf_bytes = uploaded.getvalue()

    header_info = extract_delivery_header(pdf_bytes)
    rows, errors = extract_sku_qty(pdf_bytes)

    for err in errors:
        st.warning(err)

    if not rows:
        st.error("SKU dan QTY tidak berhasil dibaca.")
        st.stop()

    missing = [r["sku"] for r in rows if r["sku"] not in master_db]
    if missing:
        st.error("SKU berikut tidak ditemukan pada database master:")
        st.code("\n".join(missing))
        st.stop()

    data = []
    for r in rows:
        m = master_db[r["sku"]]
        data.append({
            "SKU": r["sku"],
            "NAMA BARANG": m["nama_produk"],
            "QTY": r["qty"],
            "HARGA (UNIT)": m["harga"],
            "DISKON (%)": 20.0
        })

    df = pd.DataFrame(data)

    st.subheader("Data hasil pembacaan")
    st.info("Informasi header dibaca otomatis dari PDF. User hanya perlu mengisi diskon per item.")

    st.write("### Header dari PDF")
    st.write({
        "Kepada": header_info["tujuan"],
        "Alamat/Area": header_info["dari"],
        "No Pesanan": header_info["no_transfer"],
        "Tanggal": header_info["tanggal"],
        "Catatan": header_info["catatan"],
    })

    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        disabled=["SKU", "NAMA BARANG", "QTY", "HARGA (UNIT)"],
        column_config={
            "DISKON (%)": st.column_config.NumberColumn(
                "DISKON (%)",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.2f%%"
            )
        }
    )

    calc_df = edited_df.copy()
    calc_df["SUBTOTAL"] = calc_df["QTY"] * calc_df["HARGA (UNIT)"]
    calc_df["NILAI DISKON"] = calc_df["SUBTOTAL"] * calc_df["DISKON (%)"] / 100
    calc_df["SETELAH DISKON"] = calc_df["SUBTOTAL"] - calc_df["NILAI DISKON"]

    st.write("### Preview perhitungan")
    st.dataframe(calc_df, use_container_width=True)

    if st.button("Generate PDF PESANAN", type="primary"):
        pdf_output = build_pdf(edited_df, header_info)
        filename = f"Pesanan_{header_info['no_transfer'] or 'hasil'}.pdf".replace("/", "-")
        st.download_button(
            "Download PDF",
            data=pdf_output,
            file_name=filename,
            mime="application/pdf"
        )
