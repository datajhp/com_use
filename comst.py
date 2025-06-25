import os
import json
import time
import requests
import streamlit as st
from PyPDF2 import PdfReader, PdfWriter
import fitz  # PyMuPDF

# 디렉토리 설정
BASE_DIR = "./"
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SPLIT_DIR = os.path.join(BASE_DIR, "splits")
JSON_DIR = os.path.join(BASE_DIR, "jsons")
RESULT_DIR = os.path.join(BASE_DIR, "results")

for d in [UPLOAD_DIR, SPLIT_DIR, JSON_DIR, RESULT_DIR]:
    os.makedirs(d, exist_ok=True)

# secrets.toml에서 API 키 불러오기
API_KEY = st.secrets["api"]["upstage_key"]
OCR_URL = "https://api.upstage.ai/v1/document-digitization"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 고급 분할 개수 추천 함수
def recommend_split_count_advanced(pdf_path):
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    avg_size_per_page = file_size_mb / total_pages if total_pages else 0

    doc = fitz.open(pdf_path)
    image_page_count = sum(1 for page in doc if page.get_images())
    image_ratio = image_page_count / total_pages if total_pages else 0
    doc.close()

    recommended = 8
    if total_pages <= 10:
        recommended = 1
    elif total_pages <= 30:
        recommended = 3
    elif total_pages <= 60:
        recommended = 6
    elif total_pages <= 100:
        recommended = 8
    elif total_pages <= 150:
        recommended = 10
    else:
        recommended = min(15, total_pages // 10)

    if avg_size_per_page > 1.5:
        recommended += 2
    elif avg_size_per_page > 1.0:
        recommended += 1

    if image_ratio > 0.7:
        recommended += 2
    elif image_ratio > 0.4:
        recommended += 1

    return min(recommended, total_pages)

# PDF 분할 범위 계산
def generate_split_ranges(total_pages, num_parts):
    base = total_pages // num_parts
    ranges = []
    for i in range(num_parts):
        start = i * base + 1
        end = (i + 1) * base if i < num_parts - 1 else total_pages
        ranges.append((start, end))
    return ranges

# PDF 분할
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

# OCR API 호출 및 저장 (재시도 포함)
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

# JSON 병합
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

# Streamlit UI
st.set_page_config(page_title="컴활 요약집 OCR 자동화", layout="wide")
st.title("📄 컴활 요약집 자동 생성기")

uploaded_file = st.file_uploader("1. PDF 파일 업로드", type="pdf")

if uploaded_file:
    pdf_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.read())
    st.success("✅ PDF 업로드 완료")

    # 추천 분할 개수
    recommended = recommend_split_count_advanced(pdf_path)
    st.info(f"🔍 추천 안전 분할 개수: {recommended}개 (페이지 수, 이미지 비율, 해상도 기준)")

    num_parts = st.slider("2. 분할 개수 선택", min_value=1, max_value=20, value=recommended)

    if st.button("3. OCR 시작"):
        st.info("🔧 PDF 분할 중...")
        split_paths = split_pdf(pdf_path, SPLIT_DIR, num_parts)
        st.success(f"📄 총 {len(split_paths)}개로 분할 완료")

        for i, path in enumerate(split_paths):
            json_path = os.path.join(JSON_DIR, f"split_{i+1}.json")
            with st.spinner(f"🔁 OCR 중: split_{i+1}.pdf"):
                success = call_api_until_success(path, json_path)
                if success:
                    st.success(f"✅ 완료: split_{i+1}")
                else:
                    st.error(f"❌ 실패: split_{i+1}")

        st.info("🧩 OCR 결과 병합 중...")
        merged_path = os.path.join(RESULT_DIR, "merged_output.json")
        merged = merge_jsons(JSON_DIR, merged_path)
        st.success("✅ 병합 완료")

        with open(merged, "rb") as f:
            st.download_button("📥 병합된 JSON 다운로드", f, file_name="merged_output.json", mime="application/json")





import streamlit as st
import json
import openai

# 기존 API Key 사용
from main import API_KEY  # 또는 별도 config.py로 분리 가능

openai.api_key = API_KEY

# 제목
st.title("🧠 컴활 요약 자동 생성기 (GPT)")

# JSON 업로드
json_file = st.file_uploader("📤 OCR 결과 merged_output.json 업로드", type="json")
if json_file:
    data = json.load(json_file)
    html_text = data["content"]["html"]

    # 과목/장 정보 입력
    subject = st.text_input("과목", "1과목")
    chapter = st.text_input("장 정보", "2장, 3장, 4장, 5장")

    sections = [
        "설정</h1>", "유·무선 네트워크 설정</h1>", "컴퓨터의 개념 및 원리</h1>", "컴퓨터의 발전 과정</h1>",
        "컴퓨터의 분류</h1>", "자료의 표현 및 처리 방식</h1>", "수의 표현 및 연산</h1>", "중앙 처리 장치</h1>",
        "기억 장치의 구성</h1>", "입출력 장치</h1>", "기타 장치</h1>", "소프트웨어</h1>", "유틸리티(Utility)</h1>",
        "프로그래밍 언어</h1>", "PC 유지와 보수</h1>", "Windows에서 PC 관리\n", "인터넷 일반</h1>",
        "인터넷 서비스</h1>", "멀티미디어의 개념\n", "멀티미디어의 운용</h1>", "정보 통신 일반</h1>",
        "정보 윤리</h1>", "컴퓨터 범죄</h1>", "바이러스 예방과 치료</h1>",
    ]

    # 절 내용 추출 함수
    def extract_section(section_title):
        start_idx = html_text.find(section_title)
        if start_idx == -1:
            return None
        next_sections = [
            html_text.find(s, start_idx + 1)
            for s in sections if html_text.find(s, start_idx + 1) != -1
        ]
        end_idx = min(next_sections) if next_sections else len(html_text)
        return html_text[start_idx:end_idx]

    # 프롬프트 생성 함수
    def make_prompt(subject, chapter, section, content):
        return f"""
당신은 컴퓨터활용능력 1급 필기 교재를 집필하는 전문 저자입니다.

지금부터 제공하는 '{subject} {chapter} {section}' 교재 원문 내용을 바탕으로 수험생이 학습하기 좋도록 **교과서 스타일의 요약 원고**를 작성해주세요. 다음 지침을 반드시 따라주세요:

1. 전체 내용을 충분히 반영하여 작성합니다.  
2. 단순 요약이 아닌, **개념 정리, 단계별 설명, 예시, 도식 형태 설명 등**을 포함합니다.  
3. 가급적이면 문단을 나눠 이해하기 쉽게 구성합니다.  
4. 제목, 소제목, 글머리표 등을 활용하여 교재처럼 체계적으로 구성해주세요.  
5. 문체는 수험 교재에 맞게 **정중하고 설명 위주**로 작성해주세요.

### 교재 원문:
{content}

### 요약 원고 (교재 형식):
"""

    # GPT 호출 함수
    def gpt_summarize(prompt):
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message["content"]

    # 절 선택
    selected_sections = st.multiselect("요약할 절을 선택하세요", options=sections, default=sections[:3])

    if st.button("📘 요약 생성"):
        all_outputs = {}
        for sec in selected_sections:
            extracted = extract_section(sec)
            if extracted:
                prompt = make_prompt(subject, chapter, sec, extracted)
                with st.spinner(f"{sec} 요약 중..."):
                    try:
                        result = gpt_summarize(prompt)
                        st.subheader(f"📘 {sec.replace('</h1>', '')}")
                        st.write(result)
                        all_outputs[sec.replace("</h1>", "").strip()] = result
                    except Exception as e:
                        st.error(f"[❌ 오류] {sec} 요약 중 에러 발생: {e}")
            else:
                st.warning(f"[!] '{sec}' 절 내용을 찾을 수 없습니다.")

        # 결과 다운로드
        if all_outputs:
            output_json = json.dumps(all_outputs, ensure_ascii=False, indent=2)
            st.download_button("📥 요약 결과 JSON 다운로드", output_json, file_name="summary_output.json", mime="application/json")

