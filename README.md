# AcciVision - Traffic Accident Detection System

## 1. Project Overview

AcciVision is a traffic accident detection and alert management web system. It uses a YOLOv8 model to analyze uploaded videos and camera frames, detect traffic accidents, save accident evidence, and route alerts to the correct user role.

The backend is built with Flask. The frontend uses HTML, CSS, and JavaScript templates. The system supports two main roles:

- Admin: manages detection, reviews alerts, and sends confirmed alerts to responders.
- Responder: receives assigned alerts and updates the response status until the case is resolved.

## 2. Main Features

- User registration and login
- Role selection for Admin and Responder accounts
- Admin dashboard
- Responder dashboard
- Accident detection from uploaded video
- Accident detection from browser camera frames
- YOLOv8 accident detection model
- Alert creation and management
- Admin review for medium-confidence accidents
- Direct responder alert for high-confidence accidents
- Responder status updates
- Accident image and video preview
- SQLite database storage
- Password hashing with Werkzeug security utilities

## 3. How Accident Detection Works

The detection model is loaded from `best.pt`, and class labels are loaded from `coco.txt`.

The system processes video or camera frames with YOLOv8. When the detected class is `accident`, the backend checks the model confidence internally and applies the following rules:

- Below 50% confidence: no confirmed accident alert is created.
- 50% to below 80% confidence: an alert is created for admin review.
- 80% confidence or above: the alert is sent directly to responders.

The confidence value is used only inside the backend for routing decisions. It is hidden from the web interface.

The model inference time is measured around the YOLO prediction step only. Upload time, page loading time, database saving time, and notification handling are not included in that timing. The measured value is stored in the accident record as `detection_time_seconds`.

## 4. Alert Workflow

Admins can review accident alerts, inspect the available accident image or source video preview, and decide how to handle each case.

Admin actions:

- Approve and send an alert to the responder dashboard
- Mark an alert as a false alarm
- Monitor responder progress from the alert management page

Responder actions:

- View assigned alerts
- Open alert details
- Preview the accident image or video
- Update the case status

Supported responder statuses:

- Pending
- Acknowledged
- En Route
- On Scene
- Resolved

## 5. Dashboard Explanation

### Admin Dashboard

The admin dashboard shows system statistics, including:

- Active alerts
- Camera availability
- Today's cases
- Average model detection time
- Recent events

The average detection card represents the average YOLO model inference time for saved detections. It does not represent human responder response time.

### Responder Dashboard

The responder dashboard shows responder-focused statistics and assigned work, including:

- Active alerts
- Today's cases
- Assigned alerts
- Pending alerts
- A bar chart showing the number of alerts by response status

## 6. Project Structure

```text
accident_web/
|-- app.py
|-- accivision.db
|-- best.pt
|-- coco.txt
|-- requirements.txt
|-- README.md
|-- static/
|   |-- accidents/
|   |   `-- accident_*.jpg
|   |-- assets/
|   |   `-- warning.mp3
|   `-- css/
|       `-- style.css
|-- templates/
|   |-- alerts.html
|   |-- detect.html
|   |-- home.html
|   |-- intro.html
|   |-- login.html
|   |-- respond.html
|   |-- responder_alert.html
|   |-- select_role.html
|   `-- sidebar.html
`-- uploads/
    `-- uploaded video files
```

## 7. Technologies Used

- Python
- Flask
- YOLOv8 / Ultralytics
- OpenCV
- SQLite
- HTML
- CSS
- JavaScript
- Werkzeug password hashing

## 8. Installation and Setup

1. Clone the project.

```bash
git clone <repository-url>
cd accident_web
```

2. Create a virtual environment.

```bash
python -m venv accident_env
```

3. Activate the virtual environment on Windows.

```bash
accident_env\Scripts\activate
```

4. Install dependencies.

```bash
pip install -r requirements.txt
```

5. Run the Flask application.

```bash
python app.py
```

6. Open the local Flask server in your browser.

```text
http://127.0.0.1:5000
```

The app runs on the configured Flask port in `app.py`.

## 9. Security Notes

- Passwords are hashed before being stored in the database.
- New passwords use Werkzeug password hashing.
- Plain-text passwords should not be stored.
- Legacy password values should be upgraded safely only after a successful login.
- Passwords should not be printed in logs or displayed in frontend pages.
- Confidence values are used internally for alert routing and hidden from the UI.
- Sensitive configuration values should stay out of frontend files.
- For production deployment, use a secure secret key, HTTPS, CSRF protection, and a production WSGI server.

## 10. System Workflow

1. User opens the system.
2. User selects a role.
3. User registers or logs in.
4. Admin uploads a video or uses camera detection.
5. YOLOv8 analyzes frames.
6. The backend checks the detected class and confidence thresholds.
7. An alert is created if the accident meets the required threshold.
8. Medium-confidence alerts go to the admin for review.
9. High-confidence alerts go directly to responders.
10. Responder views assigned alerts.
11. Responder updates the case status until it is resolved.

## 11. Notes and Limitations

- Detection quality depends on the accuracy of `best.pt`.
- Low-confidence accidents below 50% are not saved as alerts.
- Snapshot saving is throttled by cooldown logic to reduce duplicate records.
- Camera support depends on browser permissions and local device availability.
- SQLite is suitable for local development and project demonstrations, but larger deployments may need a production database.
- This system is intended for academic or project demonstration unless deployed with production-grade security settings.
