import streamlit as st
import requests
import os
import json
import textwrap
from dotenv import load_dotenv
import time
import base64

from pixieduster.core import call_gemini, chat_gemini
from pixieduster.prompts import (
    ANTI_AI_PROMPT_TEMPLATE,
    HUMOR_INSTRUCTION,
    PERSONA_RUBRIC,
    QUESTION_SCHEMA,
    QUESTIONS_INSTRUCTION,
)

st.set_page_config(page_title="PixieDuster", layout="centered", page_icon="logo.png")

# Load environment variables (for local development)
load_dotenv(override=True)

if "api_key" not in st.session_state:
    st.session_state.api_key = os.environ.get("GEMINI_API_KEY")

if not st.session_state.api_key:
    st.markdown("<h3 style='text-align: center; color: #ffd700;'><i class='fa-solid fa-wand-magic-sparkles'></i> PixieDuster Authentication</h3>", unsafe_allow_html=True)
    st.write("To use this serverless app, please enter your Gemini API Key. It remains strictly in your browser and is never stored.")
    with st.form("auth_form"):
        user_key = st.text_input("Gemini API Key:", type="password")
        submitted = st.form_submit_button("Unlock PixieDuster", use_container_width=True)
        if submitted and user_key:
            st.session_state.api_key = user_key
            st.rerun()
    st.stop()

api_key = st.session_state.api_key

model_id = 'gemini-3.6-flash'

def _as_file_tuples(uploaded_files):
    """Adapt Streamlit UploadedFile objects to core's (name, mimetype, bytes)."""
    return [
        (f.name, f.type or "application/octet-stream", f.getvalue())
        for f in (uploaded_files or [])
    ]


# Improved CSS for better contrast and layout
st.markdown("""
<style>
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css');
@import url('https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700&family=Inter:wght@300;400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

h1, h2, h3 {
    font-family: 'Cinzel Decorative', cursive !important;
    color: #ffd700 !important; 
    text-shadow: 0 0 15px rgba(255, 215, 0, 0.4);
    text-align: center;
}

/* Background gradient - high contrast */
.stApp {
    background: radial-gradient(circle at top, #2b1845, #0f081c);
    color: #ffffff;
}

/* Animated Pixie Dust Falling Effect */
@keyframes dustFall {
  from { background-position: 0px 0px; }
  to { background-position: 0px 1000px; }
}

.stApp::before {
    content: "";
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background-image: 
        radial-gradient(2px 2px at 40px 60px, rgba(255,215,0,0.8), rgba(0,0,0,0)),
        radial-gradient(2px 2px at 150px 120px, rgba(255,255,255,0.8), rgba(0,0,0,0)),
        radial-gradient(3px 3px at 250px 200px, rgba(255,215,0,0.6), rgba(0,0,0,0)),
        radial-gradient(1px 1px at 300px 40px, rgba(255,255,255,0.8), rgba(0,0,0,0)),
        radial-gradient(2px 2px at 80px 250px, rgba(255,215,0,0.8), rgba(0,0,0,0));
    background-repeat: repeat;
    background-size: 350px 350px;
    animation: dustFall 25s linear infinite;
    pointer-events: none;
    z-index: 0;
}

/* Primary buttons */
.stButton>button {
    background: linear-gradient(135deg, #ffd700, #daa520) !important;
    border: none !important;
    border-radius: 30px !important;
    font-family: 'Cinzel Decorative', cursive !important;
    font-size: 1.2rem !important;
    font-weight: bold !important;
    padding: 10px 24px !important;
    box-shadow: 0 4px 15px rgba(218, 165, 32, 0.4) !important;
    transition: all 0.3s ease !important;
    width: 100%;
}

.stButton>button, .stButton>button p, .stButton>button div {
    color: #0f081c !important; /* Force dark text for contrast on the gold button */
}

.stButton>button:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 25px rgba(218, 165, 32, 0.6) !important;
    color: #000000 !important;
}

/* Uploader styling */
[data-testid="stFileUploadDropzone"] {
    background-color: rgba(255, 255, 255, 0.05);
    border: 2px dashed #daa520;
    border-radius: 15px;
}
[data-testid="stFileUploadDropzone"]:hover {
    border-color: #ffd700;
    background-color: rgba(255, 255, 255, 0.1);
}


/* Hide default Streamlit running animation */
[data-testid="stStatusWidget"] {
    display: none !important;
    visibility: hidden !important;
}

/* Make inputs legible with high contrast */
.stTextInput>div>div>input, .stSelectbox>div>div>div {
    background-color: rgba(0, 0, 0, 0.5) !important;
    color: white !important;
    border: 1px solid rgba(218, 165, 32, 0.5) !important;
}

/* Chat container */
[data-testid="stChatMessage"] {
    background: rgba(0, 0, 0, 0.4);
    border-radius: 15px;
    border-left: 4px solid #ffd700;
    padding: 15px;
    margin-bottom: 10px;
}

/* Form headers and labels */
label {
    color: #e2d1f9 !important;
    font-weight: 600 !important;
    font-size: 1.1rem !important;
}
p {
    font-size: 1.1rem;
    color: #d1c4e9;
}

/* Mobile Optimization */
@media (max-width: 768px) {
    h1, h2, h3 { font-size: 1.6rem !important; }
    h4 { font-size: 1.2rem !important; }
    p, label, .stInfo { font-size: 0.95rem !important; }
    
    /* Scale logo down for mobile */
    .mobile-logo { width: 180px !important; }
    
    .stButton>button {
        font-size: 1rem !important;
        padding: 12px !important;
    }
    
    [data-testid="stChatMessage"] {
        padding: 10px;
    }
}
</style>
""", unsafe_allow_html=True)


# Encode logo for centered HTML
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

logo_b64 = get_base64_image("logo.png")
st.markdown(f"<div style='text-align: center; margin-bottom: 20px;'><img class='mobile-logo' src='data:image/png;base64,{logo_b64}' width='250' style='filter: drop-shadow(0px 0px 15px rgba(255,215,0,0.3));'></div>", unsafe_allow_html=True)

st.markdown("<h3 style='text-align: center; margin-top: 0;'>Your Fairy Prompt-Mother</h3>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>Upload writing samples and let the magic extract a unique voice for your AI companion.</p>", unsafe_allow_html=True)
st.write("---")

# State Management
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'questions_data' not in st.session_state:
    st.session_state.questions_data = None
if 'uploaded_genai_files' not in st.session_state:
    st.session_state.uploaded_genai_files = []
if 'final_prompt' not in st.session_state:
    st.session_state.final_prompt = ""
if 'target_name' not in st.session_state:
    st.session_state.target_name = ""

# --- STEP 1: UPLOAD ---
if st.session_state.step == 1:
    # Visual Process Steps (instead of plain text)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-file-arrow-up fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>1. Upload</b><br><small>Drop text or PDFs.</small></div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-brain fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>2. Analyze</b><br><small>Answer AI questions.</small></div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div style='background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; text-align:center;'><i class='fa-solid fa-wand-magic-sparkles fa-2x' style='color:#daa520; margin-bottom:10px;'></i><br><b>3. Clone</b><br><small>Download the prompt.</small></div>", unsafe_allow_html=True)

    st.write("---")
    
    # Clean, linear layout instead of erratic columns
    st.markdown("### 1. Identify the Persona")
    target_input = st.text_input(
        "Whose voice are we cloning?", 
        placeholder="e.g., Myself, A 1920s detective, My best friend Sarah..."
    )
    target_name = target_input if target_input else "the author"
    
    st.markdown("### 2. Upload Writing Samples")
    with st.expander("💡 What makes a perfect sample?", expanded=True):
        st.write("For the most accurate psychological profiling, we recommend **3 to 5 samples** across different contexts:")
        st.markdown(
            "- **Informal:** A chat log, casual email, or social media post.\n"
            "- **Formal:** An essay, professional report, or dissertation.\n"
            "- **Multimodal:** We accept text files, PDFs, and even **screenshots of handwriting or chat bubbles** (PNG/JPG)!"
        )

    uploaded_files = st.file_uploader(
        "Drop files here", 
        accept_multiple_files=True, 
        type=['txt', 'pdf', 'png', 'jpg', 'jpeg'],
        label_visibility="collapsed"
    )

    st.write("---")
    analyze_btn = st.button("Begin Analysis", use_container_width=True)

    if analyze_btn:
        if uploaded_files:
            st.session_state.target_name = target_name
            with st.status("Running Analysis...", expanded=True) as status:
                try:
                    st.markdown("<i class='fa-solid fa-magnifying-glass fa-beat-fade' style='color:#ffd700;'></i> Inspecting your writing samples...", unsafe_allow_html=True)
                    # Convert UploadedFile objects to raw tuples (name, type, bytes) immediately
                    # so they survive when the file_uploader widget is unmounted in Step 2.
                    file_tuples = _as_file_tuples(uploaded_files)
                    st.session_state.uploaded_genai_files = file_tuples
                    
                    st.markdown("<i class='fa-solid fa-list-check fa-flip' style='color:#ffd700;'></i> Formulating profiling questions...", unsafe_allow_html=True)
                    prompt_instruction = QUESTIONS_INSTRUCTION.format(
                        target_name=target_name, n=3
                    )

                    time.sleep(0.1) # Force UI to render before blocking network request
                    
                    response_text = call_gemini(
                        api_key,
                        model_id,
                        prompt_instruction,
                        files=file_tuples,
                        schema=QUESTION_SCHEMA,
                    )
                    clean_text = response_text.strip()
                    if clean_text.startswith("```json"): clean_text = clean_text[7:]
                    elif clean_text.startswith("```"): clean_text = clean_text[3:]
                    if clean_text.endswith("```"): clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    try:
                        st.session_state.questions_data = json.loads(clean_text)
                    except json.JSONDecodeError as e:
                        raise Exception("The AI generated a malformed JSON payload (likely an unescaped quote). Please click 'Begin Analysis' again to let it retry!")
                    status.update(label="Analysis Complete!", state="complete", expanded=False)
                    time.sleep(0.5) 
                    
                    st.session_state.step = 2
                    st.rerun()
                    
                except Exception as e:
                    status.update(label="Analysis Failed", state="error")
                    st.error(f"An error occurred: {e}")
        else:
            st.warning("Please upload at least one writing sample.")

# --- STEP 2: INTERACTIVE Q&A ---
elif st.session_state.step == 2:
    st.subheader("Clarifying the Magic")
    st.write(f"To perfectly calibrate '{st.session_state.target_name}', please select the most accurate answers below:")
    
    user_selections = []
    
    # Render multiple choice questions
    if isinstance(st.session_state.questions_data, list):
        questions = st.session_state.questions_data
    elif isinstance(st.session_state.questions_data, dict):
        questions = st.session_state.questions_data.get('questions', [])
    else:
        questions = []
    for i, q in enumerate(questions):
        st.markdown(f"**{i+1}. {q['question']}**")
        ans = st.radio(f"Options for Q{i+1}", q['options'], key=f"q_{i}", label_visibility="collapsed")
        user_selections.append(f"Q: {q['question']}\nA: {ans}")
        st.write("") # spacing
        
    user_answers_formatted = "\n\n".join(user_selections)
    
    st.write("---")
    st.markdown("#### 🎭 Persona Tuning Levers")
    humor_level = st.slider(
        "Humor Level (Benign Violation Theory)", 
        min_value=0, max_value=10, value=5, 
        help="Adjusts how often the persona attempts humor using McGraw's Benign Violation Theory (simultaneously violating a norm while remaining benign/safe)."
    )
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Go Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        if st.button("Generate Final Prompt"):
            if user_answers_formatted:
                with st.status("Generating Final Persona...", expanded=True) as status:
                    try:
                        st.markdown("<i class='fa-solid fa-pen-nib fa-bounce' style='color:#ffd700;'></i> Compiling persona data...", unsafe_allow_html=True)
                        
                        final_instruction = (
                            f"Here are the original writing samples for '{st.session_state.target_name}'. "
                            f"I also asked the user some multiple choice questions to refine the persona.\n"
                            f"Here are their answers:\n{user_answers_formatted}\n\n"
                            + HUMOR_INSTRUCTION.format(humor_level=humor_level)
                            + "\n\n"
                            + PERSONA_RUBRIC
                        )
                        
                        st.markdown("<i class='fa-solid fa-brain fa-pulse' style='color:#ffd700;'></i> Evaluating Big Five personality traits...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-chart-bar fa-beat' style='color:#ffd700;'></i> Analyzing LIWC syntax and pronoun orientation...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-puzzle-piece fa-spin' style='color:#ffd700;'></i> Assessing cognitive style...", unsafe_allow_html=True)
                        time.sleep(0.4)
                        st.markdown("<i class='fa-solid fa-comments fa-fade' style='color:#ffd700;'></i> Mapping sociolinguistics...", unsafe_allow_html=True)

                        time.sleep(0.1) # Force UI to render before blocking network request
                        
                        extracted_persona = call_gemini(
                            api_key,
                            model_id,
                            final_instruction,
                            files=st.session_state.uploaded_genai_files,
                        )
                        
                        st.session_state.final_prompt = ANTI_AI_PROMPT_TEMPLATE.replace("{extracted_persona}", extracted_persona)
                        
                        status.update(label="Persona Generated Successfully!", state="complete", expanded=False)
                        time.sleep(0.5)
                        
                        st.session_state.step = 3
                        st.rerun()
                    except Exception as e:
                        status.update(label="Analysis Failed", state="error")
                        st.error(f"An error occurred: {e}")
            else:
                st.warning("Please provide some answers to help the AI.")

# --- STEP 3: FINAL DELIVERABLE & CHAT ---
elif st.session_state.step == 3:
    st.success("Your Custom Persona Prompt is Ready!")
    
    # Downloads
    col_md, col_pdf, col_reset = st.columns(3)
    
    with col_md:
        st.download_button(
            label="Download as .MD",
            data=st.session_state.final_prompt,
            file_name="pixiedust_prompt.md",
            mime="text/markdown"
        )
    with col_reset:
        if st.button("Start Over"):
            st.session_state.clear()
            st.rerun()

    with st.expander("View Generated Persona Certificate", expanded=True):
        import re
        import html
        
        safe_prompt = html.escape(st.session_state.final_prompt)
        
        # Replace headers
        html_prompt = re.sub(r'(?m)^### (.*?)$', r'<h4 style="color:#e2d1f9; margin-top:20px; font-family:\'Inter\', sans-serif !important;">\1</h4>', safe_prompt)
        html_prompt = re.sub(r'(?m)^## (.*?)$', r'<h3 style="color:#ffd700 !important; border-bottom: 1px solid rgba(255,215,0,0.2); padding-bottom: 5px; margin-top:25px; text-align: left !important; font-family:\'Cinzel Decorative\', cursive !important;">\1</h3>', html_prompt)
        html_prompt = re.sub(r'(?m)^# (.*?)$', r'<h2 style="color:#ffd700 !important; margin-top:30px; text-align:center !important; font-family:\'Cinzel Decorative\', cursive !important;">\1</h2>', html_prompt)
        
        # Replace bold
        html_prompt = re.sub(r'\*\*(.*?)\*\*', r'<strong style="color: #ffd700;">\1</strong>', html_prompt)
        
        # Replace italics
        html_prompt = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html_prompt)
        
        # Replace list items
        html_prompt = re.sub(r'(?m)^\* (.*?)$', r'<li style="margin-left: 20px; margin-bottom: 8px;">\1</li>', html_prompt)
        html_prompt = re.sub(r'(?m)^- (.*?)$', r'<li style="margin-left: 20px; margin-bottom: 8px;">\1</li>', html_prompt)
        
        # Wrap paragraphs
        paragraphs = html_prompt.split('\n\n')
        wrapped_paragraphs = []
        for p in paragraphs:
            if '<h' in p or '<li' in p:
                wrapped_paragraphs.append(p.replace('\n', ''))
            else:
                wrapped_paragraphs.append(f'<p style="margin-bottom: 15px; font-family:\'Inter\', sans-serif !important;">{p.replace(chr(10), "<br>")}</p>')
        
        html_prompt = "".join(wrapped_paragraphs)
        
        certificate_html = f'''
        <div style="border: 2px solid rgba(255,215,0,0.5); padding: 40px; background: linear-gradient(135deg, #160a24, #2b1845); color: #ffffff; text-align: left; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.5), inset 0 0 20px rgba(255,215,0,0.05);">
           
           <div style="text-align: center; margin-bottom: 30px;">
               <img src="data:image/png;base64,{logo_b64}" width="120" style="margin-bottom: 15px; filter: drop-shadow(0px 0px 10px rgba(255,215,0,0.4));">
               <h1 style="color: #ffd700 !important; font-family: 'Cinzel Decorative', cursive !important; margin:0; font-size: 32px; text-shadow: 0 0 10px rgba(255,215,0,0.5) !important; text-align: center !important;">CERTIFICATE OF PERSONA</h1>
               <p style="font-family: 'Inter', sans-serif !important; font-size: 16px; color: #d1c4e9 !important; margin-top: 10px; text-align: center !important;">Officially cloned for: <b style="color: #ffd700;">{st.session_state.target_name.upper()}</b></p>
           </div>
           
           <hr style="border: 0; height: 1px; background: linear-gradient(to right, transparent, rgba(255,215,0,0.5), transparent); margin: 30px 0;">
           
           <div style="font-family: 'Inter', sans-serif !important; font-size: 15px; line-height: 1.8; color: #ffffff;">
               {html_prompt}
           </div>
           
           <div style="margin-top: 50px; text-align: center;">
               <hr style="border: 0; height: 1px; background: linear-gradient(to right, transparent, rgba(255,215,0,0.3), transparent); margin-bottom: 20px;">
               <p style="font-family: 'Cinzel Decorative', cursive !important; color: #ffd700 !important; font-size: 18px; text-shadow: 0 0 8px rgba(255,215,0,0.4) !important; text-align: center !important;"><i class='fa-solid fa-certificate'></i> Authorized by PixieDuster</p>
           </div>
        </div>
        '''
        st.markdown(certificate_html, unsafe_allow_html=True)

    st.write("---")
    st.subheader("Test Your New Persona")
    st.write("Chat with the AI using your newly generated system prompt to see how it sounds!")

    if 'chat_history' not in st.session_state:
        st.session_state['chat_history'] = []
        
    for message in st.session_state['chat_history']:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_input := st.chat_input("Say something to your AI companion..."):
        st.session_state['chat_history'].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response_text = chat_gemini(api_key, model_id, st.session_state.final_prompt, st.session_state['chat_history'][:-1], user_input)
                    st.markdown(response_text)
                    st.session_state['chat_history'].append({"role": "assistant", "content": response_text})
                except Exception as e:
                    st.error(f"Chat error: {e}")
