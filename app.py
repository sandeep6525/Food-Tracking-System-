import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, joinedload
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import pandas as pd
import requests

from models import Base, User, Customer, Shipment, Timeline, TomatoType
from rules import travel_days, tomato_recommendations, suggest_tomato_type_simple
from utils import haversine_km, plan_eta, osrm_route

load_dotenv()

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev')
    db_url = os.getenv('DATABASE_URL', 'sqlite:///tomatotrack.db')
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    login_manager = LoginManager(app)
    login_manager.login_view = 'login'

    class AuthUser(UserMixin):
        def __init__(self, row: User):
            self.id = str(row.id)
            self.email = row.email
            self.role = row.role

    @login_manager.user_loader
    def load_user(user_id):
        with Session() as s:
            row = s.get(User, int(user_id))
            return AuthUser(row) if row else None

    # ---- Seeders ----
    def seed_admin():
        with Session() as s:
            admin_email = os.getenv('ADMIN_EMAIL')
            admin_pwd = os.getenv('ADMIN_PASSWORD')
            if admin_email and admin_pwd:
                existing = s.execute(select(User).where(User.email == admin_email)).scalar_one_or_none()
                if not existing:
                    u = User(email=admin_email, password_hash=generate_password_hash(admin_pwd), role='admin')
                    s.add(u)
                    s.commit()

    def seed_tomato_types():
        defaults = [
            dict(name='Green Tomato',  best_temp_min=15, best_temp_max=35, max_travel_days=10, notes='Good for long travel, ripens later'),
            dict(name='Red Tomato',    best_temp_min=15, best_temp_max=30, max_travel_days=3,  notes='Ready to eat, short distance'),
            dict(name='Cherry Tomato', best_temp_min=18, best_temp_max=28, max_travel_days=2,  notes='Fragile, fast delivery needed'),
            dict(name='Roma Tomato',   best_temp_min=12, best_temp_max=32, max_travel_days=5,  notes='Good for cooking, medium travel ok'),
        ]
        with Session() as s:
            if s.query(TomatoType).count() == 0:
                for d in defaults:
                    s.add(TomatoType(**d))
                s.commit()

    seed_admin()
    seed_tomato_types()

    # ---- Weather ----
    def get_weather(lat: float, lon: float):
        api_key = os.getenv('OPENWEATHER_API_KEY')
        if not api_key:
            return None
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            r = requests.get(url, timeout=8)
            j = r.json()
            temp = j.get('main', {}).get('temp')
            cond_main = (j.get('weather') or [{}])[0].get('main', '').lower()
            if cond_main in ('rain', 'thunderstorm', 'drizzle'):
                rain_risk = 'high'
            elif cond_main in ('clouds',):
                rain_risk = 'medium'
            else:
                rain_risk = 'low'
            return {'temp': temp, 'condition': cond_main, 'rain_risk': rain_risk}
        except Exception:
            return None

    # ---- Suggestions ----
    def choose_tomato_type(s, days: float, avg_temp_c: float, rain_risk: str):
        candidates = s.query(TomatoType).all()
        best = None
        best_score = None
        for t in candidates:
            temp_ok = (t.best_temp_min is None or avg_temp_c is None or avg_temp_c >= t.best_temp_min) and                           (t.best_temp_max is None or avg_temp_c is None or avg_temp_c <= t.best_temp_max)
            days_ok = (t.max_travel_days is None or days is None or days <= t.max_travel_days)
            if temp_ok and days_ok:
                temp_dev = 0 if avg_temp_c is None else max(
                    0,
                    (t.best_temp_min or avg_temp_c) - avg_temp_c,
                    avg_temp_c - (t.best_temp_max or avg_temp_c)
                )
                score = (t.max_travel_days or 999) - (days or 0) + (10 - temp_dev)
                if best is None or score > best_score:
                    best = t
                    best_score = score
        if best:
            return best.name
        return suggest_tomato_type_simple(days, avg_temp_c, rain_risk)

    # ---- Routes ----
    @app.route('/')
    @login_required
    def dashboard():
        with Session() as s:
            shipments = (s.query(Shipment)
                           .options(joinedload(Shipment.customer))
                           .order_by(Shipment.id.desc())
                           .limit(10).all())
            total_shipments = s.query(Shipment).count()
            in_transit = s.query(Shipment).filter(Shipment.status == 'in_transit').count()
            delivered = s.query(Shipment).filter(Shipment.status == 'delivered').count()
            # touch relationships to avoid DetachedInstanceError in template
            recent = []
            for sh in shipments:
                recent.append({
                    'id': sh.id,
                    'title': sh.title,
                    'customer_name': sh.customer.name if sh.customer else '',
                    'status': sh.status,
                    'distance_km': sh.distance_km or 0,
                    'eta_days': sh.eta_days or 0
                })
        return render_template('dashboard.html',
                               total_shipments=total_shipments,
                               in_transit=in_transit,
                               delivered=delivered,
                               recent=recent)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            with Session() as s:
                row = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
                if row and check_password_hash(row.password_hash, password):
                    login_user(AuthUser(row))
                    return redirect(url_for('dashboard'))
            flash('Invalid credentials', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        logout_user()
        return redirect(url_for('login'))

    def admin_required():
        if not (current_user.is_authenticated and getattr(current_user, 'role', 'user') == 'admin'):
            flash('Admin only', 'warning')
            return False
        return True

    @app.route('/admin/users', methods=['GET', 'POST'])
    @login_required
    def admin_users():
        if not admin_required():
            return redirect(url_for('dashboard'))
        with Session() as s:
            if request.method == 'POST':
                email = request.form['email']
                role = request.form.get('role', 'user')
                password = request.form['password']
                if not email or not password:
                    flash('Email & password required', 'danger')
                else:
                    u = User(email=email, role=role, password_hash=generate_password_hash(password))
                    s.add(u)
                    s.commit()
                    flash('User created', 'success')
            users = s.query(User).all()
        return render_template('admin_users.html', users=users)

    @app.route('/customers')
    @login_required
    def customers_list():
        with Session() as s:
            customers = s.query(Customer).all()
        return render_template('customers_list.html', customers=customers)

    @app.route('/customers/new', methods=['GET', 'POST'])
    @login_required
    def customer_new():
        if request.method == 'POST':
            with Session() as s:
                c = Customer(
                    name=request.form['name'],
                    contact=request.form.get('contact'),
                    address=request.form.get('address'),
                    notes=request.form.get('notes')
                )
                s.add(c)
                s.commit()
                return redirect(url_for('customers_list'))
        return render_template('customer_form.html', customer=None)

    @app.route('/shipments')
    @login_required
    def shipments_list():
        with Session() as s:
            rows = (s.query(Shipment)
                      .options(joinedload(Shipment.customer))
                      .order_by(Shipment.id.desc()).all())
            shipments = [{
                'id': r.id,
                'title': r.title,
                'customer_name': r.customer.name if r.customer else '',
                'tomato_type': r.tomato_type or '',
                'origin': r.origin_name,
                'destination': r.dest_name,
                'distance_km': r.distance_km,
                'status': r.status
            } for r in rows]
        return render_template('shipments_list.html', shipments=shipments)

    @app.route('/shipments/new', methods=['GET', 'POST'])
    @login_required
    def shipment_new():
        with Session() as s:
            types = [t.name for t in s.query(TomatoType).order_by(TomatoType.name).all()]
        if request.method == 'POST':
            return save_or_update_shipment()
        return render_template('shipment_form.html', shipment=None, tomato_types=types)

    @app.route('/shipments/<int:sid>/edit', methods=['GET', 'POST'])
    @login_required
    def shipment_edit(sid):
        with Session() as s:
            sh = s.get(Shipment, sid)
            types = [t.name for t in s.query(TomatoType).order_by(TomatoType.name).all()]
        if request.method == 'POST':
            return save_or_update_shipment(sid)
        return render_template('shipment_form.html', shipment=sh, tomato_types=types)

    def parse_dt(val: str):
        if not val:
            return None
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromtimestamp(int(val))
        except Exception:
            return None

    @app.route('/api/geocode')
    @login_required
    def api_geocode():
        q = request.args.get('q', '')
        if not q:
            return jsonify({'ok': False, 'error': 'query required'}), 400
        try:
            url = f'https://nominatim.openstreetmap.org/search?format=json&limit=1&q={q}'
            r = requests.get(url, headers={'User-Agent': 'TomatoTrack/1.0'}, timeout=8)
            arr = r.json()
            if not arr:
                return jsonify({'ok': False, 'error': 'not found'}), 404
            it = arr[0]
            return jsonify({'ok': True, 'lat': float(it['lat']), 'lon': float(it['lon']), 'display_name': it['display_name']})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

    def save_or_update_shipment(sid=None):
        form = request.form
        origin_name = form['origin_name']
        dest_name = form['dest_name']

        lat1 = float(form['origin_lat']); lon1 = float(form['origin_lng'])
        lat2 = float(form['dest_lat']);   lon2 = float(form['dest_lng'])

        # Try OSRM for road distance/time
        route = osrm_route(lat1, lon1, lat2, lon2)
        if route:
            distance_km, duration_hours = route
        else:
            distance_km = haversine_km(lat1, lon1, lat2, lon2)
            duration_hours = distance_km / float(os.getenv('DEFAULT_AVG_SPEED_KMPH', '50'))

        speed = float(os.getenv('DEFAULT_AVG_SPEED_KMPH', '50'))
        hours = float(os.getenv('DEFAULT_DRIVE_HOURS_PER_DAY', '8'))
        days = travel_days(distance_km, speed, hours)

        planned_start = parse_dt(form.get('planned_start'))
        planned_arrival = plan_eta(planned_start, days)

        w = get_weather(lat2, lon2)

        with Session() as s:
            if sid:
                shipment = s.get(Shipment, sid)
            else:
                shipment = Shipment(created_by=int(current_user.id))

            shipment.title = form['title']
            shipment.tomato_type = form.get('tomato_type')
            shipment.quantity_kg = float(form.get('quantity_kg') or 0)

            shipment.origin_name = origin_name
            shipment.origin_lat = lat1
            shipment.origin_lng = lon1
            shipment.dest_name = dest_name
            shipment.dest_lat = lat2
            shipment.dest_lng = lon2

            shipment.distance_km = round(distance_km, 2)
            shipment.drive_time_hours = round(duration_hours, 2)
            shipment.eta_days = round(days, 2)

            shipment.planned_start = planned_start
            shipment.planned_arrival = planned_arrival

            if w:
                shipment.avg_temp_c = w.get('temp')
                shipment.rain_risk = w.get('rain_risk')
            else:
                shipment.avg_temp_c = float(form.get('avg_temp_c') or 0)
                shipment.rain_risk = form.get('rain_risk')

            shipment.road_type = form.get('road_type')
            shipment.condition_departure = form.get('condition_departure')
            shipment.status = form.get('status', 'planned')
            cid = form.get('customer_id')
            shipment.customer_id = int(cid) if cid else None

            s.add(shipment)
            s.commit()
            flash('Shipment saved', 'success')
            return redirect(url_for('shipment_detail', sid=shipment.id))

    @app.route('/shipments/<int:sid>')
    @login_required
    def shipment_detail(sid):
        with Session() as s:
            sh = s.get(Shipment, sid)
            if not sh:
                flash('Not found', 'danger')
                return redirect(url_for('shipments_list'))
            days = sh.eta_days or 0
            recs, predicted = tomato_recommendations(
                sh.distance_km or 0,
                days,
                sh.avg_temp_c or 0,
                sh.rain_risk or 'low',
                sh.road_type or 'highway'
            )
            tomato_suggestion = choose_tomato_type(s, days, sh.avg_temp_c, sh.rain_risk)
        return render_template('shipment_detail.html',
                               shipment=sh,
                               recs=recs,
                               predicted=predicted,
                               tomato_suggestion=tomato_suggestion)

    @app.route('/shipments/<int:sid>/status', methods=['POST'])
    @login_required
    def update_status(sid):
        new_status = request.form['status']
        note = request.form.get('note', '')
        now = datetime.utcnow()
        with Session() as s:
            sh = s.get(Shipment, sid)
            if not sh:
                flash('Not found', 'danger')
                return redirect(url_for('shipments_list'))
            sh.status = new_status
            if new_status == 'in_transit' and not sh.actual_start:
                sh.actual_start = now
            if new_status == 'delivered':
                sh.delivered_at = now
            s.add(Timeline(shipment_id=sid, note=f"{new_status}: {note}"))
            s.commit()
        flash('Status updated', 'success')
        return redirect(url_for('shipment_detail', sid=sid))

    @app.route('/reports')
    @login_required
    def reports():
        return render_template('reports.html')

    @app.route('/reports/export.xlsx')
    @login_required
    def export_excel():
        with Session() as s:
            rows = (s.query(Shipment).options(joinedload(Shipment.customer)).all())
            data = [{
                'ID': r.id,
                'Title': r.title,
                'Customer': r.customer.name if r.customer else '',
                'Tomato Type': r.tomato_type or '',
                'Source': r.origin_name,
                'Destination': r.dest_name,
                'Distance (km)': r.distance_km,
                'Drive Time (hours)': r.drive_time_hours,
                'ETA (days)': r.eta_days,
                'Planned Start': r.planned_start,
                'Planned Arrival': r.planned_arrival,
                'Avg Temp (°C)': r.avg_temp_c,
                'Rain Risk': r.rain_risk,
                'Road Type': r.road_type,
                'Status': r.status,
                'Delivered At': r.delivered_at
            } for r in rows]

        if not data:
            data = [{
                'ID': '', 'Title': '', 'Customer': '', 'Tomato Type': '',
                'Source': '', 'Destination': '', 'Distance (km)': '',
                'Drive Time (hours)': '', 'ETA (days)': '', 'Planned Start': '',
                'Planned Arrival': '', 'Avg Temp (°C)': '', 'Rain Risk': '',
                'Road Type': '', 'Status': '', 'Delivered At': ''
            }]

        df = pd.DataFrame(data)
        out = 'tomatotrack_report.xlsx'
        df.to_excel(out, index=False)
        return send_file(out, as_attachment=True)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)
