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
st.title("📄 OCR 자동화기기")

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





from openai import OpenAI

client = OpenAI(api_key=st.secrets["openai"]["api_key"])

# 제목
st.title("🧠 컴활 요약집 원고 자동 생성기 (GPT)")

# JSON 업로드
json_file = st.file_uploader("📤 OCR 결과 merged_output.json 업로드", type="json")
if json_file:
    data = json.load(json_file)
    html_text = data["content"]["html"]

    # 과목/장 정보 입력
    subject = st.text_input("과목", "1과목")
    chapter = st.text_input("장 정보", "2장, 3장, 4장, 5장")

    sections = [
        "Windows의 기초", "바탕 화면", "파일 탐색기", "Windows 보조프로그램", "인쇄", "설정</h1>", "유·무선 네트워크 설정</h1>", "컴퓨터의 개념 및 원리</h1>", "컴퓨터의 발전 과정</h1>",
        "컴퓨터의 분류</h1>", "자료의 표현 및 처리 방식</h1>", "수의 표현 및 연산</h1>", "중앙 처리 장치</h1>",
        "기억 장치의 구성</h1>", "입출력 장치</h1>", "기타 장치</h1>", "소프트웨어</h1>", "유틸리티(Utility)</h1>",
        "프로그래밍 언어</h1>", "PC 유지와 보수</h1>", "Windows에서 PC 관리\n", "인터넷 일반</h1>",
        "인터넷 서비스</h1>", "멀티미디어의 개념\n", "멀티미디어의 운용</h1>", "정보 통신 일반</h1>",
        "정보 윤리</h1>", "컴퓨터 범죄</h1>", "바이러스 예방과 치료</h1>","스프레드시트 개요</h1>",
    "파일 관리</h1>",
    "워크시트의 관리</h1>",
    "데이터 입력</h1>",
    "일러스트레이션</h1>",
    "[Excel 옵션] 대화 상자</h1>",
    "데이터 편집</h1>",
    "셀 편집</h1>",
    "셀 서식 및 사용자 지정 표시 형식</h1>",
    "서식 설정\n",
    "수식의 기본 사용법\n",
    "셀 참조</h1>",
    "함수의 기본 개념\n",
    "수학과 삼각 함수/날짜와 시간 함수\n",
    "문자열 함수</h1>",
    "찾기와 참조 함수</h1>",
    "D 함수/재무 함수/정보 함수</h1>",
    "배열과 배열 수식</h1>",
    "배열 함수\n",
    "정렬</h1>",
    "필터 기능</h1>",
    "기타 데이터 관리 기능</h1>",
    "데이터 가져오기</h1>",
    "부분합/데이터 표/데이터 통합</h1>",
    "피벗 테이블</h1>",
    "피벗 차트</h1>",
    "목표값 찾기/시나리오</h1>",
    "인쇄\n합격",
    "페이지 설정</h1>",
    "리본 메뉴와 창 다루기</h1>",
    "차트의 기본</h1>",
    "차트의 종류</h1>",
    "차트 편집</h1>",
    "차트의 요소 추가와 서식 지정</h1>",
    "매크로 작성</h1>",
    "VBA 프로그래밍의 기본 개념</h1>",
    "VBA 문법\n",
    "개체 속성 및 컨트롤 속성</h1>","데이터베이스의 개념과 용어</h1>",
    "데이터베이스 설계</h1>",
    "액세스 사용의 기초</h1>",
    "테이블 생성</h1>",
    "테이블 수정</h1>",
    "필드 속성 1-속성과 형식</h1>",
    "필드 속성 2-입력 마스크/조회 속성</h1>",
    "필드 속성 3-유효성 검사/기타 필드<br>속성/기본키/인덱스</h1>",
    "필드 속성 4-관계 설정/참조 무결성</h1>",
    "데이터 입력</h1>",
    "데이터 내보내기</h1>",
    "쿼리(Query)</h1>",
    "단순 조회 쿼리(SQL문)</h1>",
    "식의 사용\n",
    "다중 테이블을 이용한 쿼리</h1>",
    "실행 쿼리(Action Query)</h1",
    "기타 데이터베이스 쿼리</h1>",
    "폼 작성 기본</h1>",
    "폼의 주요 속성</h1>",
    "하위 폼</h1>",
    "컨트롤의 사용 1-컨트롤의 개념/<br>컨트롤 만들기</h1>",
    "컨트롤의 사용 2-컨트롤 다루기/<br>컨트롤의 주요 속성</h1>",
    "폼 작성 기타</h1>",
    "보고서 작성과 인쇄</h1>",
    "보고서 구역 및 그룹화</h1>",
    "다양한 보고서 작성</h1>",
    "보고서 작성 기타</h1>",
    "매크로의 활용 1<br>매크로 함수의 개념/매크로 만들기</h1>",
    "매크로의 활용 2-<br>실행/수정/주요 매크로 함수</h1>",
    "VBA를 이용한 모듈 작성</h1>"
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
        from openai import OpenAI
        client = OpenAI(api_key=st.secrets["openai"]["api_key"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content

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



import streamlit as st
import json
import re
from openai import OpenAI

# 🔐 API Key from secrets.toml
client = OpenAI(api_key=st.secrets["openai"]["api_key"])
GPT_MODEL = "gpt-4o"

st.title("📘 요약 원고 저장 + 교재 스타일 가공")

# ✅ 1단계: JSON 업로드 또는 이전 단계에서 자동 전달
st.header("① 요약 원고 불러오기")

uploaded_json = st.file_uploader("📤 요약 결과 JSON 업로드 (또는 자동 생성)", type="json")

if "summary_json" not in st.session_state:
    st.session_state.summary_json = None

if uploaded_json:
    st.session_state.summary_json = json.load(uploaded_json)
elif st.session_state.summary_json:
    st.success("✅ 이전 단계에서 자동으로 요약 데이터를 불러왔습니다.")
else:
    st.warning("요약 JSON 파일을 업로드하거나 이전 단계에서 생성해주세요.")

# ✅ 2단계: 저장 가능한 TXT 변환
if st.session_state.summary_json:
    json_data = st.session_state.summary_json
    sections_txt = ""

    for i, (title, content) in enumerate(json_data.items()):
        sections_txt += f"\n\n===== {title} 요약 결과 =====\n\n{content}\n"

    # 저장 버튼
    st.download_button(
        "📥 요약 결과 TXT 다운로드",
        sections_txt,
        file_name="summary_output.txt",
        mime="text/plain"
    )

    st.download_button(
        "📥 원본 JSON 다운로드",
        json.dumps(json_data, ensure_ascii=False, indent=2),
        file_name="summary_output.json",
        mime="application/json"
    )

    st.markdown("---")

    # ✅ 3단계: 자동 연결 (2차 가공)
    st.header("② GPT 기반 교재 스타일 다듬기")

    # 섹션 나누기
    def extract_sections(text):
        split_sections = re.split(r'^={5}.*?={5}\s*$', text, flags=re.MULTILINE)
        titles = re.findall(r'^={5}\s*(.*?)\s*(?:</h1>)?\s*요약 결과\s*={5}', text, flags=re.MULTILINE)
        return list(zip(titles, [s.strip() for s in split_sections if s.strip()]))

    sections = extract_sections(sections_txt)
    st.success(f"✅ 총 {len(sections)}개 절을 가공합니다.")

    results = {}
    for i, (title, content) in enumerate(sections):
        with st.expander(f"📘 [{i+1}] {title} - GPT 재작성"):
            with st.spinner(f"🔁 GPT로 '{title}' 다듬는 중..."):
                try:
                    # gpt 재작성 함수
                    def ask_gpt(title, content):
                        prompt = f"[문단 제목]\n{title}\n\n[내용]\n{content}"
                        system_prompt = """
당신은 교재를 집필하는 저자입니다. 아래 원고 문단은 교재의 일부입니다.  
각 문단은 완결된 단원으로 책에 들어갈 수 있도록 **완성된 출판용 레이아웃과 서술 방식**으로 작성하세요.

[중요 지침]
1. 실제 교재 구성 형태로 출력하세요.
2. 핵심 개념, 상세 설명, 표/도식, 학습 도우미 등 구조로 작성하세요.
3. 이미지가 필요한 경우, 위치/설명/크기/캡션 포함

[출력 포맷]
📘 단원 제목: {문단 제목} / 난이도:⭐⭐⭐⭐⭐
## ✨ 핵심 개념
- ...
## 📖 상세 설명
...
"""
                        response = client.chat.completions.create(
                            model=GPT_MODEL,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt}
                            ],
                            max_tokens=2000,
                            temperature=0.3
                        )
                        return response.choices[0].message.content.strip()

                    refined = ask_gpt(title, content)
                    st.markdown(refined, unsafe_allow_html=True)
                    results[title] = refined

                except Exception as e:
                    st.error(f"❌ 오류: {e}")

    # 최종 결과 저장
    if results:
        full_refined_txt = ""
        for title, body in results.items():
            full_refined_txt += f"\n\n===== {title} 요약 결과 =====\n\n{body}\n"

        st.download_button(
            "📥 최종 교재 스타일 TXT 다운로드",
            full_refined_txt,
            file_name="refined_textbook.txt",
            mime="text/plain"
        )

        st.download_button(
            "📥 최종 JSON 다운로드",
            json.dumps(results, ensure_ascii=False, indent=2),
            file_name="refined_textbook.json",
            mime="application/json"
        )


