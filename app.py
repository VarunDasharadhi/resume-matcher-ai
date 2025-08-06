from flask import Flask, render_template, request, send_file
import os
from utils.parser import extract_text_from_pdf
from dotenv import load_dotenv
import openai
from openai import OpenAI
from utils.pdf_exporter import export_analysis_to_pdf, export_cover_letter_to_pdf


# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def analyze_with_gpt(resume_text, job_description):
    client = OpenAI()  # uses your .env OPENAI_API_KEY

    prompt = f"""
You are a resume reviewer.

Given the following RESUME and JOB DESCRIPTION:

RESUME:
{resume_text}

JOB DESCRIPTION:
{job_description}

Analyze the match. Output the following in clear format:
1. Match Score (0 to 100)
2. Matching Skills
3. Missing Skills
4. Suggestions to improve the resume for this job
"""

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=600
    )

    return response.choices[0].message.content

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        resume_file = request.files['resume']
        job_description = request.form['job_description']

        # Save resume
        resume_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_file.filename)
        resume_file.save(resume_path)

        # Extract text from resume
        resume_text = extract_text_from_pdf(resume_path)

        # Analyze with GPT
        gpt_result = analyze_with_gpt(resume_text, job_description)
        export_analysis_to_pdf(gpt_result)

        return render_template('result.html',
                               resume=resume_text,
                               job_description=job_description,
                               gpt_output=gpt_result)
    return render_template('index.html')

@app.route('/download')
def download_pdf():
    # You could also store in session or reprocess, but here we assume fixed file
    return send_file("uploads/match_result.pdf", as_attachment=True)

@app.route('/generate-cover-letter', methods=['POST'])
def generate_cover_letter():
    resume_text = request.form['resume']
    job_description = request.form['job_description']

    client = OpenAI()
    prompt = f"""
Generate a professional cover letter based on the following:

RESUME:
{resume_text}

JOB DESCRIPTION:
{job_description}

Requirements:
- Address it to 'Hiring Manager'
- Mention relevant skills from the resume
- Keep it polite, formal, and clear
- Don't exceed 250 words
"""

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        max_tokens=500
    )

    cover_letter = response.choices[0].message.content
    export_cover_letter_to_pdf(cover_letter)
    return render_template('cover_letter.html', cover_letter=cover_letter)


@app.route('/download-cover-letter')
def download_cover_letter():
    return send_file("uploads/cover_letter.pdf", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
