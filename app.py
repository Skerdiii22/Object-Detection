from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_bcrypt import Bcrypt
from flask_mail import Mail, Message
import pymysql.cursors
import random
import time
from datetime import datetime, timedelta
from ultralytics import YOLO
import torch
import os
from werkzeug.utils import secure_filename
import cv2
import pandas



# Initialize the app, bcrypt, and mail
app = Flask(__name__)
app.secret_key = 'your_secret_key'
bcrypt = Bcrypt(app)

# Configure file upload
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Load YOLOv8 model
model = YOLO('./models/yolov8n.pt')


# Configure Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'animaldetection.app1@gmail.com'  # Your email address
app.config['MAIL_PASSWORD'] = 'rnmk wyeh fsfe oovz'  # Your email password
mail = Mail(app)

import re

# Define a list of animal names
ANIMAL_NAMES = [
    "cat", "dog", "bird", "cow", "horse", "sheep", "elephant", "tiger",
    "lion", "bear", "deer", "fox", "rabbit", "wolf", "giraffe", "zebra",
    "kangaroo", "monkey", "snake", "fish", "dolphin", "whale", "shark",
    # Add more animal names as needed
]


def send_email1(user_id, animal):
    if animal.lower() not in ANIMAL_NAMES:
        return  # Skip sending an email if it's not an animal

    try:
        # Fetch email using user_id
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            result = cursor.fetchone()

        if result and result['email']:
            email = result['email']
            msg = Message(
                'Animal Detected!',
                sender='animaldetection.app1@gmail.com',
                recipients=[email]
            )
            msg.body = f'The animal "{animal}" was detected by the camera.'
            mail.send(msg)
        else:
            print(f"No email found for user_id: {user_id}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_photo', methods=['GET', 'POST'])
def upload_photo():
    detected_animal = None  # To store the detected animal name

    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not allowed_file(file.filename):
            flash('Invalid file type or no file uploaded.', 'danger')
            return redirect(request.url)

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            results = model(filepath)

            # Check detections and ensure only animals are considered
            if results[0].boxes:
                detections = results[0].boxes.cpu().numpy()  # Convert to NumPy array
                confidences = results[0].boxes.conf.cpu().numpy()
                class_ids = results[0].boxes.cls.cpu().numpy()
                class_names = results[0].names

                # Check for animals only
                for i, class_id in enumerate(class_ids):
                    class_name = class_names[int(class_id)]
                    if class_name in ANIMAL_NAMES:  # Use predefined animal array
                        detected_animal = class_name
                        confidence = confidences[i]

                        # Save to upload history
                        conn = get_db_connection()
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "INSERT INTO upload_history (user_id, image_path, predicted_animal, confidence_score, upload_time, result_status) VALUES (%s, %s, %s, %s, %s, %s)",
                                (session['user_id'], filepath, detected_animal, confidence, datetime.now(), 'success')
                            )
                            conn.commit()
                        break

            flash('Photo processed successfully!', 'success' if detected_animal else 'No animal detected.')
        except Exception as e:
            flash(f"Error processing photo: {e}", 'danger')

        return render_template('ui.html', detected_animal=detected_animal)

    return render_template('ui.html', detected_animal=None)


@app.route('/open_camera', methods=['GET'])
def open_camera():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cap = cv2.VideoCapture(0)
    timeout = datetime.now() + timedelta(minutes=5)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or datetime.now() > timeout:
            break

        results = model(frame)
        detections = results[0]

        if detections.boxes is not None:
            boxes = detections.boxes.xyxy.cpu().numpy()
            confidences = detections.boxes.conf.cpu().numpy()
            class_ids = detections.boxes.cls.cpu().numpy()
            class_names = detections.names

            for i in range(len(boxes)):
                x1, y1, x2, y2 = map(int, boxes[i])
                confidence = float(confidences[i])
                class_name = class_names[int(class_ids[i])]

                # ✅ INSERT DETECTION INTO DATABASE
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO real_time_detections (user_id, detected_animal, confidence_score, timestamp)
                            VALUES (%s, %s, %s, NOW())
                        """, (session['user_id'], class_name, confidence))
                    conn.commit()  # ✅ Make sure to commit the transaction
                except Exception as e:
                    print(f"Database insert error: {e}")
                finally:
                    conn.close()

                # ✅ Send Email Alert
                send_email1(session['user_id'], class_name)

        cv2.imwrite('static/detected_frame.jpg', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return redirect(url_for('main'))


@app.route('/upload_history', methods=['GET', 'POST'])
def upload_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    selected_query = request.form.get('query_option', 'default')

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if selected_query == "inner_join":
                cursor.execute("""
                    SELECT users.username, upload_history.image_path, upload_history.predicted_animal, upload_history.confidence_score, upload_history.upload_time 
                    FROM users,upload_history 
                    INNER JOIN upload_history ON users.id = upload_history.user_id
                    WHERE users.id = %s
                """, (session['user_id'],))
            elif selected_query == "left_join":
                cursor.execute("""
                    SELECT users.username, upload_history.image_path, upload_history.predicted_animal, upload_history.confidence_score, upload_history.upload_time 
                    FROM users, upload_history
                    LEFT JOIN upload_history ON users.id = upload_history.user_id
                    WHERE users.id = %s
                """, (session['user_id'],))
            elif selected_query == "nested_query":
                cursor.execute("""
                    SELECT * FROM users 
                    WHERE id IN (SELECT user_id FROM upload_history WHERE confidence_score > 0.8)
                """)
            elif selected_query == "aggregation":
                cursor.execute("""
                    SELECT predicted_animal, COUNT(*) AS detection_count 
                    FROM upload_history 
                    WHERE user_id = %s
                    GROUP BY predicted_animal 
                    ORDER BY detection_count DESC
                """, (session['user_id'],))
            else:
                cursor.execute("""
                    SELECT image_path, predicted_animal, confidence_score, upload_time 
                    FROM upload_history 
                    WHERE user_id = %s
                    ORDER BY upload_time DESC
                """, (session['user_id'],))

            history = cursor.fetchall()
    except Exception as e:
        flash(f"Database error: {e}", 'danger')
        history = []
    finally:
        conn.close()

    return render_template('upload_history.html', history=history, selected_query=selected_query)

@app.route('/real_time_analysis')
def real_time_analysis():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Query 1: Count total detections per animal
            cursor.execute("""
                SELECT detected_animal, COUNT(*) AS total_detections
                FROM real_time_detections 
                WHERE user_id = %s 
                GROUP BY detected_animal 
                ORDER BY total_detections DESC
            """, (session['user_id'],))
            animal_counts = cursor.fetchall()

            # Query 2: Find the most recent detection for each animal
            cursor.execute("""
                SELECT cd.detected_animal, cd.confidence_score, cd.detection_time
                FROM real_time_detections cd
                WHERE cd.detection_time = (
                    SELECT MAX(detection_time)
                    FROM real_time_detections
                    WHERE detected_animal = cd.detected_animal
                )
                ORDER BY cd.detection_time DESC;
            """)
            latest_detections = cursor.fetchall()

            # 🔹Query 3: Find the animal with the **highest confidence score**
            cursor.execute("""
                SELECT detected_animal, confidence_score
                FROM real_time_detections
                WHERE confidence_score = (SELECT MAX(confidence_score) FROM real_time_detections)
            """)
            highest_confidence = cursor.fetchone()

    except Exception as e:
        flash(f"Database error: {e}", 'danger')
        animal_counts, latest_detections, highest_confidence = [], [], None
    finally:
        conn.close()

    return render_template('real_time_analysis.html',
                           animal_counts=animal_counts,
                           latest_detections=latest_detections,
                           highest_confidence=highest_confidence)






def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

def is_valid_username(username):
    return username.isalnum() and not username.isdigit()


# Database connection
def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',  # MySQL username
        password='',  # MySQL password
        database='Diploma',  # database name
        cursorclass=pymysql.cursors.DictCursor
    )


# Routes
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if not is_valid_username(username):
            flash("Username must include at least one letter and cannot be only numbers.", "danger")
            return render_template('signup.html')

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "danger")
            return render_template('signup.html')

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (username, email, hashed_password)
                )
                conn.commit()
                flash('Account created successfully! Please log in.', 'success')
                return redirect(url_for('login'))
        except Exception as e:
            flash(f"Error: {e}", 'danger')
        finally:
            conn.close()
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                if user and bcrypt.check_password_hash(user['password_hash'], password):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    flash('Login successful!', 'success')
                    return redirect(url_for('main'))
                else:
                    flash('Invalid credentials. Please try again.', 'danger')
        except Exception as e:
            flash(f"Error: {e}", 'danger')
        finally:
            conn.close()
    return render_template('login.html')


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                if user:
                    # Generate a 5-digit verification code
                    code = str(random.randint(10000, 99999))
                    expires_at = datetime.now() + timedelta(minutes=15)  # Code expires in 15 minutes

                    # Insert the reset request into the database
                    cursor.execute(
                        "INSERT INTO password_reset_requests (email, reset_code, expires_at) VALUES (%s, %s, %s)",
                        (email, code, expires_at)
                    )
                    conn.commit()

                    # Send the code via email
                    msg = Message('Password Reset Code', sender='your_email@gmail.com', recipients=[email])
                    msg.body = f'Your 5-digit password reset code is: {code}'
                    mail.send(msg)

                    flash('A password reset code has been sent to your email.', 'info')
                    return redirect(url_for('reset_password'))
                else:
                    flash('No account found with that email address.', 'danger')
        except Exception as e:
            flash(f"Error: {e}", 'danger')
        finally:
            conn.close()
    return render_template('forgot_password.html')


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        entered_code = request.form['code']
        new_password = request.form['new_password']

        # Check if the entered code is valid and not expired
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM password_reset_requests WHERE reset_code = %s AND expires_at > NOW()",
                    (entered_code,)
                )
                reset_request = cursor.fetchone()

                if reset_request:
                    # Check if the code matches
                    if entered_code == reset_request['reset_code']:
                        # Hash the new password
                        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')

                        # Update the password in the users table
                        cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s",
                                       (hashed_password, reset_request['email']))
                        conn.commit()

                        # Remove the reset request from the table
                        cursor.execute("DELETE FROM password_reset_requests WHERE id = %s", (reset_request['id'],))
                        conn.commit()

                        flash("Password updated successfully!", 'success')
                        return redirect(url_for('login'))
                    else:
                        flash("Invalid code. Please try again.", 'danger')
                else:
                    flash("Code expired or invalid. Please request a new one.", 'danger')
        except Exception as e:
            flash(f"Error: {e}", 'danger')
        finally:
            conn.close()

    return render_template('reset_password.html')


@app.route('/main')
def main():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return f"Welcome {session['username']}! You are logged in."


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
