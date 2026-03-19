import streamlit as st
import datetime
import requests
import matplotlib.pyplot as plt
import os
import json
import csv
import pandas as pd
from io import StringIO
import hashlib
import sqlite3
from pathlib import Path

# ---- HIDDEN API KEY (from file) ----
_API_KEY = None
if os.path.exists("apikey.txt"):
    with open("apikey.txt", "r") as f:
        _API_KEY = f.read().strip()

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Create users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Create user settings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            default_city TEXT,
            default_weight REAL,
            default_height REAL,
            default_age INTEGER,
            notification_enabled BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Password hashing
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# User authentication functions
def register_user(username, password, email=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        password_hash = hash_password(password)
        c.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            (username, password_hash, email)
        )
        user_id = c.lastrowid
        
        # Create default settings
        c.execute(
            "INSERT INTO user_settings (user_id) VALUES (?)",
            (user_id,)
        )
        
        conn.commit()
        return True, "Registration successful!"
    except sqlite3.IntegrityError:
        return False, "Username already exists!"
    except Exception as e:
        return False, f"Registration failed: {str(e)}"
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        password_hash = hash_password(password)
        c.execute(
            "SELECT user_id, username FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        user = c.fetchone()
        
        if user:
            # Update last login
            c.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user[0],)
            )
            conn.commit()
            return True, {"user_id": user[0], "username": user[1]}
        else:
            return False, "Invalid username or password!"
    finally:
        conn.close()

def get_user_settings(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute(
            "SELECT default_city, default_weight, default_height, default_age, notification_enabled FROM user_settings WHERE user_id = ?",
            (user_id,)
        )
        settings = c.fetchone()
        if settings:
            return {
                "default_city": settings[0] or "",
                "default_weight": settings[1] or 70.0,
                "default_height": settings[2] or 1.75,
                "default_age": settings[3] or 30,
                "notification_enabled": bool(settings[4])
            }
        return None
    finally:
        conn.close()

def update_user_settings(user_id, settings):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE user_settings 
            SET default_city = ?, default_weight = ?, default_height = ?, default_age = ?, notification_enabled = ?
            WHERE user_id = ?
        ''', (
            settings.get("default_city", ""),
            settings.get("default_weight", 70.0),
            settings.get("default_height", 1.75),
            settings.get("default_age", 30),
            settings.get("notification_enabled", True),
            user_id
        ))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Failed to update settings: {e}")
        return False
    finally:
        conn.close()

# User-specific data functions
def get_user_data_file(user_id):
    return f"user_data_{user_id}.json"

def load_user_history(user_id):
    data_file = get_user_data_file(user_id)
    try:
        if os.path.exists(data_file):
            with open(data_file, "r") as f:
                return json.load(f)
    except:
        pass
    return []

def save_user_history(user_id, history):
    data_file = get_user_data_file(user_id)
    try:
        with open(data_file, "w") as f:
            json.dump(history, f, indent=4)
    except:
        pass

def load_user_streak(user_id):
    streak_file = f"user_streak_{user_id}.json"
    try:
        if os.path.exists(streak_file):
            with open(streak_file, "r") as f:
                return json.load(f)
    except:
        pass
    return {"last_date": None, "streak": 0}

def save_user_streak(user_id, streak_data):
    streak_file = f"user_streak_{user_id}.json"
    try:
        with open(streak_file, "w") as f:
            json.dump(streak_data, f, indent=4)
    except:
        pass

def update_user_streak(user_id, score):
    try:
        streak_data = load_user_streak(user_id)
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if score >= 90:
            if streak_data.get("last_date") == today_str:
                return streak_data.get("streak", 0)
            elif streak_data.get("last_date") == (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d"):
                streak_data["streak"] = streak_data.get("streak", 0) + 1
            else:
                streak_data["streak"] = 1
            streak_data["last_date"] = today_str
            save_user_streak(user_id, streak_data)
        else:
            streak_data["streak"] = 0
            save_user_streak(user_id, streak_data)
        return streak_data.get("streak", 0)
    except:
        return 0

# --- HELPER FUNCTIONS ---
def calculate_bmi(weight, height):
    try:
        return weight / (height ** 2)
    except:
        return 0

def age_factor(age):
    if age <= 17: return 0.9
    elif 18 <= age <= 45: return 1.0
    elif 46 <= age <= 60: return 1.1
    else: return 1.2

def get_weather_humidity(city):
    try:
        if _API_KEY:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={_API_KEY}&units=metric"
            response = requests.get(url, timeout=5).json()
            humidity = response.get("main", {}).get("humidity", 50)
            temp = response.get("main", {}).get("temp", None)
            return humidity, temp
    except:
        st.warning("⚠ Failed to get humidity from API. Using default 50%.")
    return 50, None

def drinks_hydration_adjustment(drinks):
    adjustment = 0
    adjustment -= drinks.get("Coffee", 0) * 0.2 / 1000
    adjustment -= drinks.get("Tea", 0) * 0.1 / 1000
    adjustment -= drinks.get("Alcohol", 0) * 0.3 / 1000
    adjustment += drinks.get("Juice", 0) / 1000
    adjustment += drinks.get("Soda", 0) / 1000
    return adjustment

def calculate_water(weight, activity, temperature, humidity, sodium_reflux, age):
    try:
        base = weight * 35 * age_factor(age)
        activity_factor = {"Low": 0, "Moderate": 300, "High": 600}.get(activity, 300)
        temp_factor = 250 if temperature and temperature > 30 else 0
        humid_factor = 150 if humidity and humidity > 70 else 0
        sodium_factor = 500 if sodium_reflux else 0
        return (base + activity_factor + temp_factor + humid_factor + sodium_factor) / 1000
    except:
        return 0

def hydration_score(taken, recommended):
    try:
        if recommended > 0:
            return min(round((taken/recommended)*100), 100)
    except:
        pass
    return 0

def hydration_category(score):
    if score >= 90: return "Optimal Hydration"
    elif score >= 75: return "Healthy Hydration"
    elif score >= 50: return "Mild Dehydration"
    else: return "Severe Dehydration"

def hydration_risk(score):
    if score >= 80: return "LOW"
    elif score >= 50: return "MODERATE"
    else: return "HIGH"

def hydration_advice(score):
    if score >= 90: return "Great job! Maintain hydration."
    elif score >= 70: return "Good hydration. Drink a little more water."
    elif score >= 50: return "You need more water today."
    else: return "Drink water immediately."

# Authentication UI
def show_login_page():
    st.title("💧 BioHydration Tracker")
    st.markdown("---")
    
    tab1, tab2 = st.tabs(["🔐 Login", "📝 Register"])
    
    with tab1:
        st.header("Login to Your Account")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                if username and password:
                    success, result = login_user(username, password)
                    if success:
                        st.session_state.authenticated = True
                        st.session_state.user = result
                        st.session_state.user_settings = get_user_settings(result["user_id"])
                        st.rerun()
                    else:
                        st.error(result)
                else:
                    st.warning("Please fill in all fields")
    
    with tab2:
        st.header("Create New Account")
        with st.form("register_form"):
            new_username = st.text_input("Choose Username")
            new_password = st.text_input("Choose Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            email = st.text_input("Email (optional)")
            
            submitted = st.form_submit_button("Register")
            
            if submitted:
                if new_username and new_password:
                    if new_password == confirm_password:
                        if len(new_password) >= 6:
                            success, message = register_user(new_username, new_password, email)
                            if success:
                                st.success(message)
                                st.info("Please login with your new account")
                            else:
                                st.error(message)
                        else:
                            st.warning("Password must be at least 6 characters")
                    else:
                        st.warning("Passwords do not match")
                else:
                    st.warning("Please fill in all required fields")

def show_settings_page():
    st.header("⚙️ User Settings")
    
    if st.session_state.user_settings:
        with st.form("settings_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                default_city = st.text_input(
                    "Default City", 
                    value=st.session_state.user_settings.get("default_city", "")
                )
                default_weight = st.number_input(
                    "Default Weight (kg)", 
                    min_value=20.0, 
                    max_value=300.0, 
                    value=st.session_state.user_settings.get("default_weight", 70.0)
                )
            
            with col2:
                default_height = st.number_input(
                    "Default Height (m)", 
                    min_value=1.0, 
                    max_value=2.5, 
                    value=st.session_state.user_settings.get("default_height", 1.75),
                    format="%.2f"
                )
                default_age = st.number_input(
                    "Default Age", 
                    min_value=1, 
                    max_value=120, 
                    value=st.session_state.user_settings.get("default_age", 30)
                )
            
            notification_enabled = st.checkbox(
                "Enable Notifications", 
                value=st.session_state.user_settings.get("notification_enabled", True)
            )
            
            submitted = st.form_submit_button("Save Settings")
            
            if submitted:
                new_settings = {
                    "default_city": default_city,
                    "default_weight": default_weight,
                    "default_height": default_height,
                    "default_age": default_age,
                    "notification_enabled": notification_enabled
                }
                
                if update_user_settings(st.session_state.user["user_id"], new_settings):
                    st.session_state.user_settings = new_settings
                    st.success("Settings saved successfully!")
                    st.rerun()

# Main app interface
def show_main_app():
    # Sidebar with user info
    with st.sidebar:
        st.title(f"👋 Welcome, {st.session_state.user['username']}!")
        
        if st.button("🚪 Logout"):
            for key in ['authenticated', 'user', 'user_settings', 'history']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
        
        st.markdown("---")
        
        # User settings in sidebar
        st.header("⚙️ Quick Settings")
        
        # Load user settings or defaults
        settings = st.session_state.user_settings
        
        age = st.number_input("Age", min_value=1, max_value=120, 
                             value=settings.get("default_age", 30) if settings else 30)
        weight = st.number_input("Weight (kg)", min_value=20.0, max_value=300.0, 
                                value=settings.get("default_weight", 70.0) if settings else 70.0)
        height = st.number_input("Height (m)", min_value=1.0, max_value=2.5, 
                                value=settings.get("default_height", 1.75) if settings else 1.75)
        
        st.markdown("---")
        st.header("📍 Location")
        city = st.text_input("City", 
                            value=settings.get("default_city", "Accra,GH") if settings else "Accra,GH")
        
        if st.button("🌤️ Get Weather"):
            with st.spinner("Fetching weather data..."):
                humidity, temp = get_weather_humidity(city)
                st.session_state.humidity = humidity
                st.session_state.temp = temp
                st.success(f"Humidity: {humidity}% | Temp: {temp if temp else 'N/A'}°C")
        else:
            if 'humidity' not in st.session_state:
                st.session_state.humidity = 50
                st.session_state.temp = None
        
        st.markdown("---")
        if st.button("⚙️ Open Full Settings"):
            st.session_state.show_settings = True
            st.rerun()

    # Main content
    if st.session_state.get('show_settings', False):
        show_settings_page()
        if st.button("← Back to Dashboard"):
            st.session_state.show_settings = False
            st.rerun()
    else:
        # Load user's history
        if 'history' not in st.session_state:
            st.session_state.history = load_user_history(st.session_state.user["user_id"])

        col1, col2 = st.columns([1, 1])

        with col1:
            st.header("📝 Today's Input")
            
            activity = st.select_slider(
                "Activity Intensity",
                options=["Low", "Moderate", "High"],
                value="Moderate"
            )
            
            sodium_reflux = st.checkbox("Sodium Reflux (burning feeling)")
            
            st.subheader("☕ Other Drinks (ml)")
            drinks_col1, drinks_col2 = st.columns(2)
            with drinks_col1:
                coffee = st.number_input("Coffee", min_value=0.0, value=0.0, step=50.0, key="coffee")
                tea = st.number_input("Tea", min_value=0.0, value=0.0, step=50.0, key="tea")
                juice = st.number_input("Juice", min_value=0.0, value=0.0, step=50.0, key="juice")
            with drinks_col2:
                soda = st.number_input("Soda", min_value=0.0, value=0.0, step=50.0, key="soda")
                alcohol = st.number_input("Alcohol", min_value=0.0, value=0.0, step=50.0, key="alcohol")
            
            drinks = {
                "Coffee": coffee,
                "Tea": tea,
                "Juice": juice,
                "Soda": soda,
                "Alcohol": alcohol
            }
            
            water_taken_ml = st.number_input("Water taken today (ml)", min_value=0.0, value=1000.0, step=100.0)

            if st.button("Calculate Hydration", type="primary"):
                # Calculate everything
                water_taken = water_taken_ml / 1000 + drinks_hydration_adjustment(drinks)
                bmi = calculate_bmi(weight, height)
                
                # BMI status
                if bmi < 18.5:
                    bmi_status = "Underweight"
                elif bmi < 25:
                    bmi_status = "Normal weight"
                elif bmi < 30:
                    bmi_status = "Overweight"
                else:
                    bmi_status = "Obese"
                
                recommended = calculate_water(weight, activity, st.session_state.temp, 
                                             st.session_state.humidity, sodium_reflux, age)
                remaining = max(recommended - water_taken, 0)
                score = hydration_score(water_taken, recommended)
                category = hydration_category(score)
                risk = hydration_risk(score)
                advice = hydration_advice(score)
                sachets = round(remaining / 0.5, 1)
                streak = update_user_streak(st.session_state.user["user_id"], score)

                # Create record
                st.session_state.current_record = {
                    "Record_Number": len(st.session_state.history) + 1,
                    "Date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Username": st.session_state.user["username"],
                    "Location": city,
                    "BMI": round(bmi, 2),
                    "BMI_status": bmi_status,
                    "Activity": activity,
                    "Recommended_Water_L": round(recommended, 2),
                    "Water_Taken_L": round(water_taken, 2),
                    "Water_to_Add_L": round(remaining, 2),
                    "Hydration_Score": score,
                    "Hydration_Status": category,
                    "Hydration_Risk": risk,
                    "Advice": advice,
                    "Sachets(500ml)": sachets,
                    "Humidity(%)": st.session_state.humidity,
                    "Streak_Days": streak,
                    "Drinks(ml)": drinks
                }
                
                # Save to user's history
                st.session_state.history.append(st.session_state.current_record)
                save_user_history(st.session_state.user["user_id"], st.session_state.history)

        with col2:
            if st.session_state.get('current_record'):
                record = st.session_state.current_record
                
                st.header("📊 Dashboard")
                
                # Key metrics
                metric_col1, metric_col2, metric_col3 = st.columns(3)
                with metric_col1:
                    st.metric("Hydration Score", f"{record['Hydration_Score']}%")
                with metric_col2:
                    st.metric("Water Taken", f"{record['Water_Taken_L']}L")
                with metric_col3:
                    st.metric("Recommended", f"{record['Recommended_Water_L']}L")
                
                st.progress(record['Hydration_Score'] / 100)
                
                # Status cards
                status_col1, status_col2 = st.columns(2)
                with status_col1:
                    st.info(f"**Status:** {record['Hydration_Status']}")
                    st.info(f"**Risk Level:** {record['Hydration_Risk']}")
                with status_col2:
                    st.success(f"**Advice:** {record['Advice']}")
                    st.warning(f"**Streak:** {record['Streak_Days']} days 🔥")
                
                # Chart
                fig1, ax1 = plt.subplots(figsize=(6, 4))
                labels = ["Water Taken", "Recommended"]
                values = [record['Water_Taken_L'], record['Recommended_Water_L']]
                colors = ["#1f77b4", "#ff7f0e"]
                bars = ax1.bar(labels, values, color=colors, edgecolor='black', alpha=0.85)
                for i, v in enumerate(values):
                    ax1.text(i, v + 0.05, f"{v} L", ha='center', fontweight='bold')
                ax1.set_ylabel("Liters")
                ax1.grid(axis='y', linestyle='--', alpha=0.6)
                st.pyplot(fig1)
                plt.close()

                if sodium_reflux:
                    with st.expander("💊 Sodium Reflux Tips"):
                        for tip in ["Drink more water", "Reduce salty foods", 
                                   "Avoid lying after meals", "Eat smaller meals", 
                                   "Limit carbonated drinks"]:
                            st.write(f"- {tip}")

        # History section
        if st.session_state.history:
            st.markdown("---")
            st.header("📈 Your Hydration History")
            
            # Show history chart
            if len(st.session_state.history) > 0:
                fig2, ax2 = plt.subplots(figsize=(10, 5))
                dates = [r.get("Date", "")[:10] for r in st.session_state.history[-10:]]  # Last 10 entries
                taken = [r.get("Water_Taken_L", 0) for r in st.session_state.history[-10:]]
                recommended = [r.get("Recommended_Water_L", 0) for r in st.session_state.history[-10:]]
                
                ax2.plot(range(len(dates)), taken, label="Water Taken 💧", 
                        color="#1f77b4", linewidth=2, marker='o')
                ax2.plot(range(len(dates)), recommended, label="Recommended Water 💦", 
                        color="#ff7f0e", linewidth=2, linestyle='--', marker='s')
                ax2.set_xticks(range(len(dates)))
                ax2.set_xticklabels(dates, rotation=45, ha='right')
                ax2.set_ylabel("Liters")
                ax2.set_title("Your Hydration History (Last 10 entries)")
                ax2.grid(True, linestyle='--', alpha=0.5)
                ax2.legend()
                plt.tight_layout()
                st.pyplot(fig2)
                plt.close()

            # Export options
            st.subheader("📥 Export Your Data")
            col_export1, col_export2 = st.columns(2)
            
            with col_export1:
                if st.button("Export Current Record"):
                    if st.session_state.get('current_record'):
                        output = StringIO()
                        writer = csv.writer(output)
                        for k, v in st.session_state.current_record.items():
                            if k != "Drinks(ml)":
                                writer.writerow([k, v])
                        for drink, amount in st.session_state.current_record["Drinks(ml)"].items():
                            writer.writerow([f"Drink_{drink}", amount])
                        
                        csv_data = output.getvalue()
                        st.download_button(
                            label="Download CSV",
                            data=csv_data,
                            file_name=f"{st.session_state.user['username']}_hydration_report.csv",
                            mime="text/csv"
                        )
            
            with col_export2:
                if st.button("Export All History"):
                    # Flatten history for export
                    flat_history = []
                    for record in st.session_state.history:
                        flat_record = {k: v for k, v in record.items() if k != "Drinks(ml)"}
                        if "Drinks(ml)" in record:
                            for drink, amount in record["Drinks(ml)"].items():
                                flat_record[f"Drink_{drink}"] = amount
                        flat_history.append(flat_record)
                    
                    df = pd.DataFrame(flat_history)
                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        label="Download All History",
                        data=csv_data,
                        file_name=f"{st.session_state.user['username']}_complete_history.csv",
                        mime="text/csv"
                    )

# Main app
def main():
    # Initialize database
    init_db()
    
    # Initialize session state
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    # Show appropriate page
    if not st.session_state.authenticated:
        show_login_page()
    else:
        show_main_app()

if __name__ == "__main__":
    main()