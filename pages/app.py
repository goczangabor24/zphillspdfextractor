import streamlit as st
import PyPDF2
import fitz  # PyMuPDF
import re
import pandas as pd
import streamlit.components.v1 as components
import io
from datetime import datetime
from pathlib import Path

# 1. Setup
st.set_page_config(page_title="Zooplus - Trixie Entry Certificates", layout="wide")
st.title("🐶 Zooplus - Trixie Entry Certificates")


# Helper function for JS Copy Button
def copy_button(label, text_to_copy):
    button_uuid = re.sub(r"\W+", "", label)
    safe_text = text_to_copy.replace("\\", "\\\\").replace("`", "\\`")
    custom_js = f"""
        <button id="{button_uuid}" style="
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;">
            📋 Copy All
        </button>
        <script>
        document.getElementById("{button_uuid}").addEventListener("click", function() {{
            const text = `{safe_text}`;
            navigator.clipboard.writeText(text).then(function() {{
                console.log('Copied!');
            }}, function(err) {{
                console.error('Could not copy text: ', err);
            }});
        }});
        </script>
    """
    components.html(custom_js, height=45)


# --- PATH DECODER ---
def extract_path_info(path):
    if not path or path == "No matching path found":
        return "Missing"

    p = str(path).replace("\\", "/")
    p = p.replace("_", "-")
    p = p.replace('"', "")

    m_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
    }

    loc_m = re.search(r"(WRO|BOR|KRO|BUD|ANR|BHX|BTS|MAD|MIL|ORY)", p, re.IGNORECASE)
    if not loc_m:
        return "Missing"

    loc = loc_m.group(1).upper()

    yr_m = re.search(r"(202[0-9]|2[0-9])", p)
    yr = yr_m.group(1) if yr_m else "2025"
    if len(yr) == 2:
        yr = "20" + yr

    mo = "01"
    for m_n, m_c in m_map.items():
        if m_n in p.lower():
            mo = m_c
            break
    else:
        num_m = re.search(loc + r"[^0-9]*([0-1][0-9])", p, re.IGNORECASE)
        if num_m:
            mo = num_m.group(1)

    return f"{loc} {mo}-{yr}"


def extract_po_numbers_from_pdf(pdf_bytes):
    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
    text_content = ""

    for page in reader.pages:
        t = page.extract_text()
        if t:
            text_content += t

    pattern = r"\b(?:[1-2]\d{6}|4[07]\d{8})\b"
    raw_pos = re.findall(pattern, text_content)

    pos = []
    for item in raw_pos:
        if item not in pos:
            pos.append(item)

    return pos


def build_results(pos, clean_paths):
    results = []

    for po in pos:
        match = "No matching path found"
        for p_str in clean_paths:
            if po in p_str:
                match = p_str
                break

        info = extract_path_info(match)
        results.append({
            "PO Number": po,
            "Matched Path": match,
            "TO_COPY": info
        })

    return results


def style_results_table(df_display):
    def highlight_missing(row):
        if str(row["TO_COPY"]).strip().lower() == "missing":
            return ["background-color: #d32f2f; color: white;" for _ in row]
        return ["" for _ in row]

    return df_display.style.apply(highlight_missing, axis=1)


def add_po_labels_to_pdf(doc, results):
    """
    PO sorokhoz hozzáírja a WAREHOUSE MM-YYYY értéket
    a lap jobb széléhez igazítva.
    """
    inserted_count = 0
    not_found = []

    font_size = 11
    y_offset = -3
    right_margin = 85

    po_map = {
        str(row["PO Number"]): str(row["TO_COPY"])
        for row in results
        if str(row["TO_COPY"]).strip().lower() != "missing"
    }

    for po, label in po_map.items():
        found_any = False

        for page in doc:
            rects = page.search_for(po)

            if rects:
                r = rects[0]

                text_width = fitz.get_text_length(label, fontname="helv", fontsize=font_size)
                x = page.rect.x1 - right_margin - text_width
                y = r.y1 + y_offset

                text_height = font_size + 5
                bg_rect = fitz.Rect(
                    x - 2,
                    r.y0 - 1,
                    x + text_width + 2,
                    r.y0 + text_height
                )

                page.draw_rect(bg_rect, color=None, fill=(1, 1, 1))
                page.insert_text(
                    (x, y),
                    label,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0)
                )

                inserted_count += 1
                found_any = True
                break

        if not found_any:
            not_found.append(po)

    return inserted_count, not_found


def add_date_and_signature(doc, signature_image_path):
    """
    1) Ausstellungsdatum alá: Wien, aktuális dátum
    2) Unterschrift... részhez: Tina Horn + aláíráskép
    """
    today_str = datetime.now().strftime("%d.%m.%Y")
    date_text = f"Wien, {today_str}"

    date_hits = 0
    sign_hits = 0

    for page in doc:
        # --- Ausstellungsdatum keresése ---
        date_rects = page.search_for("Ausstellungsdatum")
        if date_rects:
            r = date_rects[0]

            # a címke alatti vonal környékére írjuk
            x = r.x0
            y = r.y1 + 18

            text_width = fitz.get_text_length(date_text, fontname="helv", fontsize=11)
            bg_rect = fitz.Rect(x - 1, y - 12, x + text_width + 2, y + 3)
            page.draw_rect(bg_rect, color=None, fill=(1, 1, 1))
            page.insert_text(
                (x, y),
                date_text,
                fontsize=11,
                fontname="helv",
                color=(0, 0, 0)
            )
            date_hits += 1

       
    return date_hits, sign_hits


def create_modified_pdf(pdf_bytes, results, signature_image_path):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    inserted_count, not_found = add_po_labels_to_pdf(doc, results)
    date_hits, sign_hits = add_date_and_signature(doc, signature_image_path)

    output_bytes = doc.tobytes()
    doc.close()

    return output_bytes, inserted_count, not_found, date_hits, sign_hits


# --- STEP 1: UPLOAD ---
st.subheader("1. Upload PDF")
pdf_file = st.file_uploader("Upload PDF to extract PO numbers", type=["pdf"])

if pdf_file is not None:
    try:
        pdf_bytes = pdf_file.read()
        pos = extract_po_numbers_from_pdf(pdf_bytes)

        if pos:
            st.success(f"Extracted {len(pos)} PO numbers in document order.")
            st.subheader("🔗 Copy & Paste to search bar")

            oder_text = " ODER ".join(pos)
            or_text = " OR ".join(pos)

            c1, c2 = st.columns(2)
            with c1:
                st.text_area("German Windows:", value=oder_text, height=100)
                copy_button("German String", oder_text)

            with c2:
                st.text_area("English Windows:", value=or_text, height=100)
                copy_button("English String", or_text)

            st.divider()
            st.subheader("2. Copy with Ctrl + Shift + C and paste paths then press Ctrl + Enter to get the results")
            path_input = st.text_area("Paste the list of paths here (one per line):", height=150)

            lines = path_input.split("\n")
            clean_p = []
            for line in lines:
                path_item = line.strip().replace('"', "")
                if path_item:
                    clean_p.append(path_item)

            results = build_results(pos, clean_p)

            st.subheader("📋 Final Results")
            df = pd.DataFrame(results)
            df_display = df[["PO Number", "TO_COPY"]].copy()

            st.dataframe(
                style_results_table(df_display),
                use_container_width=True,
                hide_index=True
            )

            csv = df_display.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.download_button(
                "📥 Download Results CSV",
                data=csv,
                file_name="trixie_results.csv",
                mime="text/csv"
            )

            st.divider()
            st.subheader("3. Generate annotated PDF")

            # Ezt a képet tedd a repo-ba is ugyanezen a néven, ha cloudon futtatod
            signature_image_path = "/mnt/data/Unterschrift Tina Horn.png"

            if st.button("✍️ Create modified PDF"):
                modified_pdf_bytes, inserted_count, not_found, date_hits, sign_hits = create_modified_pdf(
                    pdf_bytes,
                    results,
                    signature_image_path
                )

                st.success(f"Done. Inserted {inserted_count} warehouse labels into the PDF.")
                st.info(f"Date fields filled: {date_hits} | Signature fields filled: {sign_hits}")

                if not_found:
                    st.warning("These PO numbers were not found in the PDF search step:")
                    st.write(", ".join(not_found))

                original_name = pdf_file.name.rsplit(".", 1)[0]
                st.download_button(
                    "📥 Download Modified PDF",
                    data=modified_pdf_bytes,
                    file_name=f"{original_name}_annotated.pdf",
                    mime="application/pdf"
                )

        else:
            st.warning("No PO numbers matching criteria were found in the PDF.")

    except Exception as e:
        st.error(f"Error: {e}")
