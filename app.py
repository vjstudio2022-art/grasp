import os
import json
import requests
import random
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from groq import Groq
from duckduckgo_search import DDGS

app = Flask(__name__)
app.secret_key = "grasp_ultra_secure_2026_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///grasp_users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    history = db.relationship('History', backref='owner', lazy=True)

class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    images = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)
    is_bookmarked = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

with app.app_context():
    db.create_all()

# --- 🛡️ THE MASTER SYSTEM PROMPT (All your old rules + Toggle Support) ---
MASTER_SYSTEM_PROMPT = """You are Grasp AI, a Master Research Assistant and Mathematics Expert.

STRUCTURE RULES:
1. Provide the response in 4 lengths using these tags: [BIT], [SHORT], [MEDIUM], [LONG].
2. In [MEDIUM] and [LONG], start directly with bullet points. No 'Answer:' heading.
3. After the [LONG] section, write the word 'Analysis:' followed by a deep, exhaustive explanation.

CONTENT RULES:
- If user asks 'X ante enti', explain in detail in the same language (Telugu/English).
- For Math: provide step-by-step (Given, Formula, Calculation).
- 'entha' and 'enti' are Telugu, not Malayalam.
"""

def get_google_style_images(query):
    imgs = []
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            q_lower = query.lower()
            if any(word in q_lower for word in ["graph", "plot", "function", "y=", "x="]):
                search_query = f"{query} mathematical function graph coordinate plane Cartesian hd labeled"
            elif any(word in q_lower for word in ["anatomy", "enti", "ante", "structure", "parts", "body"]):
                search_query = f"{query} anatomical diagram labeling hd labeled structure chart educational visualization"
            else:
                search_query = f"{query} educational diagram labeled visualization hd"

            search_results = list(ddgs.images(keywords=search_query, region="wt-wt", safesearch="off", max_results=3, size="Medium", type_image="photo"))
            if search_results:
                imgs = [r['image'] for r in search_results]
        return imgs
    except Exception as e:
        return []
    

@app.route('/get_pdf_content', methods=['POST'])
def get_pdf_content():
    try:
        data = request.get_json()
        if not data or 'question' not in data:
            return jsonify({"success": False, "msg": "No question provided"}), 400
            
        q = data.get('question')
        
        # Timeout ni 60 seconds ki penchandi, endukante Research Thesis ki time paduthundi
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", # Limit thaggalante chinna model vadandi
            messages=[
                {"role": "system", "content": "You are a professional researcher. Provide an exhaustive, detailed report with headings."},
                {"role": "user", "content": f"Write a full research thesis on: {q}"}
            ],
            timeout=60.0 
        )
        
        full_detail = completion.choices[0].message.content
        return jsonify({"success": True, "detailed_content": full_detail})

    except Exception as e:
        print(f"PDF Error: {str(e)}") # Idi terminal lo error chupisthundi
        return jsonify({"success": False, "msg": str(e)}), 500

@app.route("/")
def home():
    user_id = session.get("user_id")
    grouped_history, bookmarks, user_name = {}, [], None
    if user_id:
        user = User.query.get(user_id)
        if user:
            user_name = user.name
            raw = History.query.filter_by(user_id=user_id).order_by(History.id.desc()).all()
            for item in raw:
                try: img_list = json.loads(item.images)
                except: img_list = []
                item_data = {"id": item.id, "question": item.question, "answer": item.answer, "images": img_list, "date": item.date, "is_bookmarked": item.is_bookmarked}
                if item.is_bookmarked: bookmarks.append(item_data)
                date_key = item.date.split(',')[0]
                if date_key not in grouped_history: grouped_history[date_key] = []
                grouped_history[date_key].append(item_data)
    return render_template("index.html", user=user_name, grouped_history=grouped_history, bookmarks=bookmarks)

@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.json
        q = data.get('question')
        user_id = session.get("user_id")
        
        # AI Response logic
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": MASTER_SYSTEM_PROMPT}, {"role": "user", "content": q}],
            timeout=25.0
        )
        ans = completion.choices[0].message.content
        imgs = get_google_style_images(q)
        date_str = datetime.now().strftime("%b %d, %Y")
        
        h_id = random.randint(100000, 999999)
        
        if user_id:
            # Check for user and then save
            user = User.query.get(user_id)
            if user:
                new_entry = History(
                    question=q, 
                    answer=ans, 
                    images=json.dumps(imgs), 
                    date=date_str, 
                    user_id=user_id,
                    is_bookmarked=False
                )
                db.session.add(new_entry)
                db.session.commit() # Commit mandatory
                h_id = new_entry.id # Database generate chesina permanent ID
                print(f"History saved successfully for user {user_id}") # Debugging
        
        return jsonify({
            "success": True, 
            "id": h_id, 
            "question": q, 
            "answer": ans, 
            "images": imgs, 
            "is_bookmarked": False,
            "date": date_str
        })
    except Exception as e:
        db.session.rollback()
        print(f"Ask Error: {str(e)}")
        return jsonify({"success": False, "msg": str(e)})

# ... (Keep other routes like login, register, bookmark, get_pdf_content as they are) ...

# --- AUTH & BOOKMARK ROUTES ---
@app.route('/bookmark', methods=['POST'])
def toggle_bookmark():
    item = History.query.get(request.json.get('id'))
    if item:
        item.is_bookmarked = not item.is_bookmarked
        db.session.commit()
        return jsonify({"success": True, "is_bookmarked": item.is_bookmarked})
    return jsonify({"success": False})

@app.route('/delete_history', methods=['POST'])
def delete_history():
    item = History.query.get(request.json.get('id'))
    if item:
        db.session.delete(item); db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/login', methods=['POST'])
def login():
    d = request.json
    u = User.query.filter_by(email=d['email']).first()
    if u and bcrypt.check_password_hash(u.password, d['password']):
        session["user_id"] = u.id
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/register', methods=['POST'])
def register():
    d = request.json
    if User.query.filter_by(email=d['email']).first(): return jsonify({"success": False})
    u = User(name=d['name'], email=d['email'], password=bcrypt.generate_password_hash(d['password']).decode('utf-8'))
    db.session.add(u); db.session.commit(); session["user_id"] = u.id
    return jsonify({"success": True})

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

if __name__ == "__main__":
   port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
