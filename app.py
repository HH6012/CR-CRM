import datetime
import os
import pandas as pd
import google.generativeai as genai 
import smtplib 
from email.mime.text import MIMEText 
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename

# --- CONFIGURE GOOGLE AI ---
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.5-pro')

# --- App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secret_key_change_this_later'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cr_sales_crm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Association Tables ---
deal_contact_association = db.Table('deal_contact_association',
    db.Column('deal_id', db.Integer, db.ForeignKey('deal.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'), primary_key=True),
    db.Column('role', db.String(100))
)

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    organizations = db.relationship('Organization', backref='owner', lazy=True)
    deals = db.relationship('Deal', backref='owner', lazy=True)
    
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(100))
    sponsorship_potential = db.Column(db.String(50), default='High (Sponsor Target)')
    strategic_notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contacts = db.relationship('Contact', backref='organization', lazy='dynamic', cascade="all, delete-orphan")
    deals = db.relationship('Deal', backref='organization', lazy='dynamic', cascade="all, delete-orphan")
    files = db.relationship('File', backref='organization', lazy='dynamic', cascade="all, delete-orphan")
    event_attendances = db.relationship('Attendee', backref='organization', lazy='dynamic', cascade="all, delete-orphan")
    custom_fields = db.relationship('CustomField', backref='organization', lazy=True, cascade="all, delete-orphan")
    files = db.relationship('File', backref='organization', lazy='dynamic', cascade="all, delete-orphan")

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    title = db.Column(db.String(200))
    email = db.Column(db.String(150))
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    interactions = db.relationship('Interaction', backref='contact', lazy='dynamic', cascade="all, delete-orphan")
    tasks = db.relationship('Task', backref='contact', lazy='dynamic', cascade="all, delete-orphan")
    deals = db.relationship('Deal', secondary=deal_contact_association, back_populates='contacts')

class Interaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    interaction_type = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    notes = db.Column(db.Text, nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Pending')
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(100))
    attendees = db.relationship('Attendee', backref='event', lazy='dynamic', cascade="all, delete-orphan")

class Attendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_type = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Integer, nullable=False, default=0)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Deal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    value = db.Column(db.Integer, default=0)
    stage = db.Column(db.String(50), nullable=False, default='Lead')
    stage_id = db.Column(db.Integer, db.ForeignKey('pipeline_stage.id'))
    closing_date = db.Column(db.Date, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contacts = db.relationship('Contact', secondary=deal_contact_association, back_populates='deals')

class PipelineStage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    order = db.Column(db.Integer, nullable=False) # To control the display order
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class CustomField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    field_name = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.String(500))
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)



# --- HELPER FUNCTIONS ---
def create_automated_task(deal, new_stage):
    contact = deal.organization.contacts.first()
    if not contact: return
    if new_stage == 'Proposal Sent':
        title = f"Follow up on proposal for {deal.name}"
        due_date = datetime.date.today() + datetime.timedelta(days=7)
        task = Task(title=title, due_date=due_date, contact_id=contact.id, user_id=current_user.id)
        db.session.add(task)
        flash(f'Automated Task Created: "{title}"', 'info')

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user is None or not user.check_password(request.form['password']):
            flash('Invalid email or password.', 'error'); return redirect(url_for('login'))
        login_user(user, remember=True)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        if User.query.filter_by(email=request.form['email']).first():
            flash('Email address already in use.', 'error'); return redirect(url_for('register'))
        user = User(username=request.form['username'], email=request.form['email'])
        user.set_password(request.form['password'])
        db.session.add(user); db.session.commit()
        flash('Congratulations, you are now a registered user!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# --- MAIN & DASHBOARD ROUTES ---
@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    open_deals_query = Deal.query.filter(Deal.user_id==current_user.id, Deal.stage.notin_(['Closed-Won', 'Closed-Lost']))
    pipeline_value = db.session.query(func.sum(Deal.value)).filter(Deal.user_id==current_user.id, Deal.stage.notin_(['Closed-Won', 'Closed-Lost'])).scalar() or 0
    return render_template('dashboard.html', pipeline_value=pipeline_value, open_deals_count=open_deals_query.count())

@app.route('/reporting')
@login_required
def reporting():
    # --- Calculate Win Rate ---
    won_deals_count = Deal.query.filter_by(user_id=current_user.id, stage='Closed-Won').count()
    lost_deals_count = Deal.query.filter_by(user_id=current_user.id, stage='Closed-Lost').count()
    total_closed_deals = won_deals_count + lost_deals_count
    win_rate = (won_deals_count / total_closed_deals * 100) if total_closed_deals > 0 else 0

    # --- Calculate Average Sales Cycle Length ---
    # Note: This is a simplified calculation
    won_deals = Deal.query.filter_by(user_id=current_user.id, stage='Closed-Won').all()
    total_days = 0
    for deal in won_deals:
        # We need a created_at field for this, let's add it. For now, we'll simulate.
        # In a real scenario, you'd calculate (deal.closing_date - deal.created_at).days
        total_days += (deal.closing_date - (deal.closing_date - datetime.timedelta(days=30))).days # Simulating a 30-day cycle
    
    avg_cycle_length = (total_days / won_deals_count) if won_deals_count > 0 else 0

    # --- Deals Won This Year ---
    deals_won_this_year = Deal.query.filter(
        Deal.user_id==current_user.id, 
        Deal.stage=='Closed-Won', 
        func.strftime('%Y', Deal.closing_date) == str(datetime.date.today().year)
    ).count()

    return render_template('reporting.html', 
                           win_rate=win_rate,
                           avg_cycle_length=avg_cycle_length,
                           deals_won_this_year=deals_won_this_year)

# --- PIPELINE & API ROUTES ---
@app.route('/pipeline')
@login_required
def pipeline():
    stages = PipelineStage.query.filter_by(user_id=current_user.id).order_by(PipelineStage.order).all()
    deals_by_stage = {stage.id: [] for stage in stages}
    deals = Deal.query.filter_by(owner=current_user).all()
    for deal in deals:
        if deal.stage_id in deals_by_stage:
            deals_by_stage[deal.stage_id].append(deal)
    return render_template('pipeline.html', deals_by_stage=deals_by_stage, stages=stages, now=datetime.datetime.utcnow())

@app.route('/api/deal/<int:deal_id>/update_stage', methods=['POST'])
@login_required
def api_update_deal_stage(deal_id):
    deal = Deal.query.get_or_404(deal_id)
    if deal.user_id != current_user.id: return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    new_stage = request.json.get('new_stage')
    if new_stage not in DEAL_STAGES: return jsonify({'success': False, 'error': 'Invalid stage'}), 400
    create_automated_task(deal, new_stage)
    deal.stage = new_stage
    deal.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'message': 'Deal stage updated.'})

# --- ORGANIZATION ROUTES ---
@app.route('/organizations')
@login_required
def organization_list():
    organizations = Organization.query.filter_by(owner=current_user).order_by(Organization.name).all()
    return render_template('organization_list.html', organizations=organizations)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
def add_organization():
    if request.method == 'POST':
        org = Organization(name=request.form['name'], country=request.form['country'], sponsorship_potential=request.form['sponsorship_potential'], strategic_notes=request.form['strategic_notes'], user_id=current_user.id)
        db.session.add(org); db.session.commit()
        return redirect(url_for('organization_list'))
    return render_template('add_organization.html')

@app.route('/org/<int:org_id>')
@login_required
def org_detail(org_id):
    org = Organization.query.filter_by(id=org_id, user_id=current_user.id).first_or_404()
    return render_template('org_detail.html', org=org)

@app.route('/org/<int:org_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_organization(org_id):
    org = Organization.query.filter_by(id=org_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        org.name = request.form['name']
        org.country = request.form['country']
        org.sponsorship_potential = request.form['sponsorship_potential']
        org.strategic_notes = request.form['strategic_notes']
        db.session.commit()
        return redirect(url_for('org_detail', org_id=org.id))
    return render_template('edit_organization.html', org=org)

@app.route('/org/<int:org_id>/upload_file', methods=['POST'])
@login_required
def upload_file(org_id):
    org = Organization.query.filter_by(id=org_id, user_id=current_user.id).first_or_404()
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(request.url)
    
    if file:
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        
        new_file = File(filename=filename, organization_id=org.id, user_id=current_user.id)
        db.session.add(new_file)
        db.session.commit()
        
        flash('File uploaded successfully', 'success')
    return redirect(url_for('org_detail', org_id=org_id))

# --- CONTACT ROUTES ---
@app.route('/org/<int:org_id>/add_contact', methods=['GET', 'POST'])
@login_required
def add_contact(org_id):
    org = Organization.query.get_or_404(org_id)
    if request.method == 'POST':
        contact = Contact(name=request.form['name'], title=request.form['title'], email=request.form['email'], org_id=org.id, user_id=current_user.id)
        db.session.add(contact); db.session.commit()
        return redirect(url_for('org_detail', org_id=org.id))
    return render_template('add_contact.html', organization=org)

@app.route('/contact/<int:contact_id>')
@login_required
def contact_detail(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    
    # --- Timeline Logic to gather all activities ---
    timeline_items = []
    
    # Add interactions to the timeline
    for interaction in contact.interactions:
        timeline_items.append({
            'type': 'Interaction',
            'item': interaction,
            'date': interaction.date
        })
        
    # Add tasks to the timeline
    for task in contact.tasks:
        timeline_items.append({
            'type': 'Task',
            'item': task,
            'date': task.due_date # Use due_date for sorting
        })

    # Sort all timeline items by date, newest first
    timeline_items.sort(key=lambda x: x['date'], reverse=True)

    return render_template('contact_detail.html', contact=contact, timeline_items=timeline_items)

@app.route('/contact/<int:contact_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_contact(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        contact.name = request.form['name']; contact.title = request.form['title']; contact.email = request.form['email']
        db.session.commit()
        return redirect(url_for('org_detail', org_id=contact.org_id))
    return render_template('edit_contact.html', contact=contact)

@app.route('/contact/<int:contact_id>/add_interaction', methods=['GET', 'POST'])
@login_required
def add_interaction(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if contact.user_id != current_user.id:
        return "Unauthorized", 403

    if request.method == 'POST':
        interaction = Interaction(
            interaction_type=request.form['interaction_type'],
            notes=request.form['notes'],
            date=datetime.datetime.utcnow(),
            contact_id=contact.id,
            user_id=current_user.id
        )
        db.session.add(interaction)
        db.session.commit()
        flash('Interaction logged.', 'success')
        return redirect(url_for('contact_detail', contact_id=contact.id))
    
    return render_template('add_interaction.html', contact=contact)

@app.route('/contact/<int:contact_id>/add_task', methods=['GET', 'POST'])
@login_required
def add_task(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if contact.user_id != current_user.id:
        return "Unauthorized", 403

    if request.method == 'POST':
        due_date = datetime.datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        task = Task(
            title=request.form['title'],
            due_date=due_date,
            contact_id=contact.id,
            user_id=current_user.id
        )
        db.session.add(task)
        db.session.commit()
        flash('Task created.', 'success')
        return redirect(url_for('contact_detail', contact_id=contact.id))
    
    return render_template('add_task.html', contact=contact)

# --- SETTINGS ROUTES ---
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        stage_name = request.form['stage_name']
        # Set order to be the next highest number
        max_order = db.session.query(func.max(PipelineStage.order)).filter_by(user_id=current_user.id).scalar() or 0
        new_stage = PipelineStage(name=stage_name, order=max_order + 1, user_id=current_user.id)
        db.session.add(new_stage)
        db.session.commit()
        flash('New pipeline stage added.', 'success')
        return redirect(url_for('settings'))

    stages = PipelineStage.query.filter_by(user_id=current_user.id).order_by(PipelineStage.order).all()
    return render_template('settings.html', stages=stages)

@app.route('/settings/stage/<int:stage_id>/delete', methods=['POST'])
@login_required
def delete_stage(stage_id):
    stage = PipelineStage.query.get_or_404(stage_id)
    if stage.user_id != current_user.id:
        return "Unauthorized", 403
    # You might want to add logic here to re-assign deals before deleting a stage
    db.session.delete(stage)
    db.session.commit()
    flash('Stage deleted.', 'success')
    return redirect(url_for('settings'))

# --- EMAIL ROUTES ---

# --- EMAIL & AI ROUTES ---

@app.route('/contact/<int:contact_id>/compose', methods=['GET', 'POST'])
@login_required
def compose_email(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    draft = ""
    if request.method == 'POST':
        purpose = request.form['purpose']
        key_points = request.form['key_points']
        
        # --- Simplified and more direct prompt ---
        prompt = f"""
        Draft a professional sales email from Hamish Harrison of Currency Research to {contact.name}, the {contact.title} at {contact.organization.name}.

        The subject of the email is: {purpose}.

        Incorporate these key points:
        {key_points}

        The tone should be confident and professional. Use an active voice and keep sentances under 20 words 
        """
        
        try:
            response = model.generate_content(prompt)
            # --- Add error handling for safety blocks ---
            if response.parts:
                draft = response.text
                flash('AI draft generated successfully!', 'success')
            else:
                flash('AI could not generate a draft. The prompt may have been blocked by safety filters. Please try rephrasing.', 'error')
                draft = "Error: AI response blocked. Please rephrase your key points."

        except Exception as e:
            flash(f'Could not generate AI draft: {e}', 'error')

    return render_template('compose_email.html', contact=contact, draft=draft)

@app.route('/contact/<int:contact_id>/send_email', methods=['POST'])
@login_required
def send_email(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    recipient_email = contact.email
    subject = request.form['subject']
    body = request.form['body']
    
    # Get email credentials from environment variables
    sender_email = os.environ.get('EMAIL_ADDRESS')
    password = os.environ.get('EMAIL_PASSWORD')
    smtp_server = os.environ.get('EMAIL_SMTP_SERVER')
    
    if not all([sender_email, password, smtp_server]):
        flash('Email credentials are not configured in the .env file.', 'error')
        return redirect(url_for('compose_email', contact_id=contact.id))

    # --- SEND EMAIL LOGIC ---
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP_SSL(smtp_server, 465) as smtp:
            smtp.login(sender_email, password)
            smtp.send_message(msg)

        # Log the email as an interaction
        interaction = Interaction(interaction_type="Email Sent", notes=f"Subject: {subject}\n\n{body}", contact_id=contact.id, user_id=current_user.id)
        db.session.add(interaction); db.session.commit()
        flash(f'Email to {contact.name} sent and logged successfully!', 'success')
        return redirect(url_for('contact_detail', contact_id=contact.id))
        
    except Exception as e:
        flash(f"Failed to send email: {e}", "error")
        return redirect(url_for('compose_email', contact_id=contact.id))

# --- DEAL ROUTES ---
@app.route('/deal/<int:deal_id>')
@login_required
def deal_detail(deal_id):
    deal = Deal.query.filter_by(id=deal_id, user_id=current_user.id).first_or_404()
    return render_template('deal_detail.html', deal=deal, stages=DEAL_STAGES)

@app.route('/org/<int:org_id>/add_deal', methods=['GET', 'POST'])
@login_required
def add_deal(org_id):
    org = Organization.query.get_or_404(org_id)
    stages = PipelineStage.query.filter_by(user_id=current_user.id).order_by(PipelineStage.order).all()
    if request.method == 'POST':
        deal = Deal(
            name=request.form['name'], value=int(request.form['value']),
            stage_id=request.form['stage_id'],
            closing_date=datetime.datetime.strptime(request.form['closing_date'], '%Y-%m-%d').date(),
            organization_id=org.id, user_id=current_user.id
        )
        db.session.add(deal); db.session.commit()
        return redirect(url_for('org_detail', org_id=org.id))
    return render_template('add_deal.html', org=org, stages=stages)

@app.route('/deal/<int:deal_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_deal(deal_id):
    deal = Deal.query.filter_by(id=deal_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        deal.name = request.form['name']
        deal.value = int(request.form['value'])
        deal.stage = request.form['stage']
        deal.closing_date = datetime.datetime.strptime(request.form['closing_date'], '%Y-%m-%d').date()
        db.session.commit()
        return redirect(url_for('deal_detail', deal_id=deal.id))
    return render_template('edit_deal.html', deal=deal, stages=DEAL_STAGES)

@app.route('/deal/<int:deal_id>/delete', methods=['POST'])
@login_required
def delete_deal(deal_id):
    deal = Deal.query.filter_by(id=deal_id, user_id=current_user.id).first_or_404()
    org_id = deal.organization_id
    db.session.delete(deal)
    db.session.commit()
    flash(f'Deal "{deal.name}" has been deleted.', 'success')
    return redirect(url_for('org_detail', org_id=org_id))

# --- EVENT MANAGEMENT ROUTES ---
@app.route('/events')
@login_required
def event_list():
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template('event_list.html', events=events)

@app.route('/events/add', methods=['GET', 'POST'])
@login_required
def add_event():
    if request.method == 'POST':
        event = Event(name=request.form['name'], date=datetime.datetime.strptime(request.form['date'], '%Y-%m-%d').date(), location=request.form['location'])
        db.session.add(event); db.session.commit()
        return redirect(url_for('event_list'))
    return render_template('add_event.html')

@app.route('/event/<int:event_id>')
@login_required
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    total_revenue = db.session.query(func.sum(Attendee.value)).filter_by(event_id=event.id).scalar() or 0
    attending_org_ids = [a.organization_id for a in event.attendees]
    potential_attendees = Organization.query.filter(Organization.user_id==current_user.id, Organization.id.notin_(attending_org_ids)).order_by(Organization.name).all()
    return render_template('event_detail.html', event=event, total_revenue=total_revenue, potential_attendees=potential_attendees)

@app.route('/event/<int:event_id>/add_attendee', methods=['POST'])
@login_required
def add_attendee(event_id):
    event = Event.query.get_or_404(event_id)
    attendee = Attendee(event_id=event.id, organization_id=request.form['organization_id'], registration_type=request.form['registration_type'], value=int(request.form['value']), user_id=current_user.id)
    db.session.add(attendee); db.session.commit()
    return redirect(url_for('event_detail', event_id=event.id))

# --- IMPORT ROUTE ---
@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_data():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'error'); return redirect(request.url)
        try:
            df = pd.read_csv(file.stream)
            required_columns = ['Org', 'Country', 'Sponsorship Potential']
            if not all(col in df.columns for col in required_columns):
                flash(f'CSV is missing columns: {", ".join(required_columns)}', 'error'); return redirect(request.url)
            count = 0
            for index, row in df.iterrows():
                if pd.notna(row['Org']):
                    exists = Organization.query.filter_by(name=row['Org'], user_id=current_user.id).first()
                    if not exists:
                        org = Organization(name=row['Org'], country=row.get('Country'), sponsorship_potential=row.get('Sponsorship Potential'), user_id=current_user.id)
                        db.session.add(org); count += 1
            db.session.commit()
            flash(f'{count} new organizations imported successfully!', 'success')
            return redirect(url_for('organization_list'))
        except Exception as e:
            flash(f'An error occurred during import: {e}', 'error'); return redirect(request.url)
    return render_template('import_data.html')
    
# --- DATABASE SETUP COMMAND ---
@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    if not User.query.filter_by(username='hamish').first():
        user = User(username='hamish', email='hamish@example.com')
        user.set_password('password')
        db.session.add(user); db.session.commit()
        print("Default user created.")
    print('Initialized the database.')