# 🚦 AcciVision — Traffic Accident Detection System

**AcciVision** is a web-based AI system that detects traffic accidents from uploaded videos and camera frames, then routes alerts through an admin and responder workflow.

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Flask](https://img.shields.io/badge/Flask-Backend-black)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-purple)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green)
![SQLite](https://img.shields.io/badge/SQLite-Database-lightgrey)
![HTML/CSS/JS](https://img.shields.io/badge/HTML%2FCSS%2FJS-Frontend-orange)

---

## 📌 Project Overview

AcciVision uses a YOLOv8 model to analyze traffic video frames and identify accident events. It is built with **Flask** for the backend and **HTML, CSS, and JavaScript** for the frontend.

The system supports two main roles:

- **Admin**: runs detection, reviews incidents, approves or rejects alerts, and monitors system activity.
- **Responder**: receives assigned alerts, views case details, and updates the response status until the case is resolved.

---

## 👥 System Roles

| Role | Main Permissions |
|------|------------------|
| Admin | Upload video, run detection, review alerts, approve/reject alerts, view dashboard |
| Responder | View assigned alerts, update response status, resolve cases |

---

## 🧰 Technologies Used

| Layer | Technology |
|------|------------|
| Backend | Flask / Python |
| AI Model | YOLOv8 / Ultralytics |
| Computer Vision | OpenCV |
| Database | SQLite |
| Frontend | HTML, CSS, JavaScript |
| Security | Werkzeug Password Hashing |

---

## 🤖 How the AI Model Works

- The YOLOv8 model is loaded from `best.pt`.
- Class labels are loaded from `coco.txt`.
- Frames are extracted from an uploaded video or browser camera input.
- Each frame is processed using YOLOv8.
- The system checks whether the detected class is `accident`.
- Confidence is used internally to decide alert routing.
- Confidence values are hidden from the web interface.

```text
Camera / Video
     |
     v
Frame Extraction
     |
     v
YOLOv8 Model Prediction
     |
     v
Class Detection: accident / cars
     |
     v
Confidence-Based Decision
     |
     v
Admin Review or Responder Alert
```

---

## 🧠 Accident Decision Logic

| Model Result | Confidence Range | System Action |
|-------------|------------------|---------------|
| Not accident / cars | Any | No alert |
| Accident | Less than 50% | No alert |
| Accident | 50% to less than 80% | Send to Admin Review |
| Accident | 80% or higher | Send directly to Responder |

> Confidence is used only inside the backend routing logic and is not shown in the user interface.

---

## 🚨 Alert Workflow

```text
Accident Detected
   |
   v
Check Confidence
   |
   +-- 50% - 79% --> Admin Review
   |                  |
   |                  +-- Admin Approves --> Sent to Responder
   |                  |
   |                  `-- Admin Rejects  --> Marked as False Alarm
   |
   `-- 80%+ --------> Sent Directly to Responder
                         |
                         v
                 Responder Updates Status
                         |
                         v
                      Resolved
```

---

## 📊 Dashboard Explanation

### 🛠️ Admin Dashboard

The admin dashboard provides a system-level overview:

- Active alerts
- Today’s cases
- Average model detection time
- Alert statistics and recent events

The average model detection time is based on YOLO inference timing, not human responder response time.

### 🚑 Responder Dashboard

The responder dashboard focuses on assigned cases:

- Active alerts
- Today’s cases
- Response status bar chart
- Assigned accident cases

---

## 🔄 Response Status Lifecycle

| Status | Meaning |
|--------|---------|
| Pending | Alert is waiting for responder action |
| Acknowledged | Responder has seen the alert |
| En Route | Responder is on the way |
| On Scene | Responder arrived at the location |
| Resolved | Case has been completed |

---

## ✨ Main Features

| Feature | Description |
|---------|-------------|
| Authentication | User registration and login with hashed passwords |
| Role Selection | Admin and Responder workflows |
| Detection Input | Uploaded video and browser camera frame processing |
| AI Detection | YOLOv8 accident detection from `best.pt` |
| Alert Routing | Internal confidence-based routing |
| Admin Review | Medium-confidence alerts can be approved or rejected |
| Responder Flow | Responders update status from Pending to Resolved |
| Evidence Preview | Accident image and uploaded video preview |
| Storage | SQLite database and saved accident snapshots |

---

## 📁 Project Structure

```text
accident_web/
|-- app.py
|-- accivision.db
|-- best.pt
|-- coco.txt
|-- requirements.txt
|-- README.md
|
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
|
|-- static/
|   |-- assets/
|   |   `-- warning.mp3
|   |-- css/
|   |   `-- style.css
|   `-- accidents/
|       `-- accident_*.jpg
|
`-- uploads/
    `-- uploaded video files
```

---

## ⚙️ Installation and Setup

1. Clone the project and enter the folder.

```bash
git clone <repository-url>
cd accident_web
```

2. Create and activate a virtual environment.

```bash
python -m venv accident_env
accident_env\Scripts\activate
```

3. Install dependencies.

```bash
pip install -r requirements.txt
```

4. Run the Flask application.

```bash
python app.py
```

5. Open the local server in your browser.

```text
http://127.0.0.1:5000
```

The app runs on the Flask port configured in `app.py`.

---

## 🔐 Security Notes

- Passwords are hashed before being stored.
- Plain-text passwords should not be stored in the database.
- Passwords should not be printed in logs or exposed in frontend pages.
- Confidence values are used internally and hidden from the UI.
- Sensitive configuration should remain outside frontend files.
- Production deployment should use HTTPS, a secure secret key, CSRF protection, and a production WSGI server.

---

## 🧭 System Workflow

| Step | Action |
|------|--------|
| 1 | User opens the system |
| 2 | User selects Admin or Responder role |
| 3 | User registers or logs in |
| 4 | Admin uploads video or starts camera detection |
| 5 | YOLOv8 analyzes frames |
| 6 | Backend checks class and confidence thresholds |
| 7 | Alert is created if the accident meets the required threshold |
| 8 | Medium-confidence alerts go to Admin Review |
| 9 | High-confidence alerts go directly to responders |
| 10 | Responder updates the case status |
| 11 | Case is marked Resolved |

---

## 📝 Notes and Limitations

- Detection accuracy depends on the quality of `best.pt`.
- Accidents below 50% confidence are not saved as alerts.
- Snapshot saving is limited by cooldown logic to reduce duplicates.
- Camera detection depends on browser permissions and device availability.
- SQLite is suitable for local development and demonstration use.
- This project should be hardened before production deployment.

