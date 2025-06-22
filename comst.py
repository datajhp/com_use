import os
import json
import time
import math
import requests
import streamlit as st
from PyPDF2 import PdfReader, PdfWriter

# API 설정
API_KEY = st.secrets["api"]["upstage_key"] # 🔐 여기에 실제 키 입력
OCR_URL = "https://api.upstage.ai/v1/document-digitization"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 경로 설정
BASE_DIR = "./"
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPLIT_DIR = os.path.join(BASE_DIR, "splits")
JSON_DIR = os.path.join(BASE_DIR, "jsons")
RESULT_DIR = os.path.join(BASE_DIR, "results")

for d in [UPLOAD_DIR, SPLIT_DIR, JSON_DIR, RESULT_DIR]:
    os.makedirs(d, exist_ok=True)

# 📌 PDF 분할 범위 계산
def generate_split_ranges(total_pages, num_parts):
    base = total_pages // num_parts
    ranges = []
    for i in range(num_parts):
        start = i * base + 1
        end = (i + 1) * base if i < num_parts - 1 else total_pages
        ranges.append((start, end))
    return ranges

# 📌 PDF 분할
def split_pdf(input_path, output_dir, num_parts):
    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    split_ranges = generate_split_ranges(total_pages, num_parts)
    split_paths = []

    for idx, (start, end) in enumerate(split_ranges):
        writer = PdfWriter()
        for page_num in range(start - 1, end):
            writer.add_page(reader.pages[page_num])
        output_pdf_path = os.path.join(output_dir, f"split_{idx+1}.pdf")
        with open(output_pdf_path, "wb") as f:
            writer.write(f)
        split_paths.append(output_pdf_path)
    return split_paths

# 📌 OCR 호출 및 저장 (성공할 때까지 반복)
def call_api_until_success(pdf_path, output_json_path, max_retries=5):
    for attempt in range(max_retries):
        try:
            with open(pdf_path, "rb") as f:
                files = {"document": f}
                data = {"ocr": "force", "base64_encoding": "['table']", "model": "document-parse"}
                response = requests.post(OCR_URL, headers=HEADERS, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                with open(output_json_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                return True
        except Exception as e:
            st.warning(f"예외 발생: {e}")
        time.sleep(2)
    return False

# 📌 결과 병합
def merge_jsons(input_dir, output_path):
    merged_html = ""
    for filename in sorted(os.listdir(input_dir)):
        if filename.endswith(".json"):
            with open(os.path.join(input_dir, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
                try:
                    html = data["content"]["html"]
                    merged_html += html + "\n"
                except KeyError:
                    st.warning(f"HTML 누락: {filename}")
    result = {"api": "2.0", "content": {"html": merged_html}}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return output_path

# 📌 Streamlit UI
st.title("📄 컴활 요약집 OCR 자동화 시스템")
uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type="pdf")

if uploaded_file:
    filename = uploaded_file.name
    input_pdf_path = os.path.join(UPLOAD_DIR, filename)
    with open(input_pdf_path, "wb") as f:
        f.write(uploaded_file.read())

    st.success("✅ PDF 업로드 완료")
    num_parts = st.slider("몇 조각으로 분할할까요?", 5, 20, 12)

    if st.button("📌 OCR 시작"):
        split_paths = split_pdf(input_pdf_path, SPLIT_DIR, num_parts)
        st.info(f"{len(split_paths)}개로 분할 완료")

        for i, path in enumerate(split_paths):
            json_path = os.path.join(JSON_DIR, f"split_{i+1}.json")
            st.write(f"📄 OCR 요청 중: split_{i+1}.pdf")
            success = call_api_until_success(path, json_path)
            if success:
                st.success(f"✅ 완료: split_{i+1}")
            else:
                st.error(f"❌ 실패: split_{i+1}")

        st.info("📦 결과 병합 중...")
        merged_path = os.path.join(RESULT_DIR, "merged_output.json")
        merged = merge_jsons(JSON_DIR, merged_path)
        st.success("✅ 병합 완료")

        with open(merged, "rb") as f:
            st.download_button("📥 병합된 JSON 다운로드", f, file_name="merged_output.json", mime="application/json")
