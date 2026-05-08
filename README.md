# 🚦 AcciVision — Traffic Accident Detection System

**AcciVision** is a web-based AI accident detection system that analyzes uploaded videos and camera frames, identifies traffic accidents with YOLOv8, and routes alerts to admins or responders based on the detection result.

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Flask](https://img.shields.io/badge/Flask-Backend-black)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-purple)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green)
![SQLite](https://img.shields.io/badge/SQLite-Database-lightgrey)
![HTML/CSS/JS](https://img.shields.io/badge/HTML%2FCSS%2FJS-Frontend-orange)

---

## 📌 Project Overview

AcciVision helps detect and manage traffic accident cases through an AI-assisted workflow.

- It uses a **YOLOv8** model to analyze frames from uploaded videos or browser camera input.
- It uses **Flask** for backend routes, authentication, detection processing, and database storage.
- It uses **HTML, CSS, and JavaScript** for the web interface.
- It supports two operational roles: **Admin** and **Responder**.

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

## 🤖 AI Model Overview

AcciVision uses a custom YOLOv8 model for traffic accident detection.

| Item | Current Project Value |
|------|------------------------|
| Model Type | YOLOv8 object detection model |
| Model File | `best.pt` |
| Labels File | `coco.txt` |
| Input Sources | Uploaded video frames and browser camera frames |
| Detected Classes Used by Project | `accident`, `cars` |
| Main Alert Class | `accident` |

The model analyzes each processed frame and returns object detections. The backend then checks the detected class and applies internal decision rules before creating or routing an alert.

---

## 🧠 How the Model Detects Accidents

1. The system receives a video frame or camera frame.
2. The frame is resized and prepared for model inference.
3. YOLOv8 runs prediction on the frame.
4. The model returns detected objects, class IDs, bounding boxes, and confidence values.
5. The backend maps class IDs to labels from `coco.txt`.
6. The backend checks whether the detected class is `accident`.
7. If the detected class is `cars`, no accident alert is created.
8. If the detected class is `accident`, the system applies internal confidence rules.
9. Based on the confidence range, the alert is ignored, sent to admin review, or sent directly to responders.

```text
Camera / Uploaded Video
        |
        v
Frame Extraction
        |
        v
YOLOv8 Model Prediction
        |
        v
Object Detection
        |
        v
Class Check: accident or cars
        |
        v
Confidence-Based Routing
        |
        v
Admin Review / Responder Alert
```

---

## 🧾 Model Decision Logic

| Detected Class | Confidence Range | System Decision |
|---------------|------------------|-----------------|
| `cars` | Any value | No alert |
| `accident` | Below 50% | No alert |
| `accident` | 50% to below 80% | Send to Admin Review |
| `accident` | 80% or above | Send directly to Responder |

> Confidence is used only inside the backend logic and is not shown in the user interface.

---

## 📦 Model Inputs and Outputs

| Item | Description |
|------|-------------|
| Input | Image/frame from camera or uploaded video |
| Model | YOLOv8 custom trained model |
| Model File | `best.pt` |
| Labels File | `coco.txt` |
| Output | Class name, bounding box, confidence value |
| Main Class Used for Alerts | `accident` |

---

## ⚙️ Model Response Time

The admin dashboard shows the **average model detection time**.

This value measures how long the YOLOv8 model takes to run inference on frames that become saved detection records. It focuses on model prediction speed only.

It does **not** mean:

- Human responder response time
- Page loading time
- Video upload time
- Database saving time
- Alert notification time

The timing is stored in the database as `detection_time_seconds` and displayed on the admin dashboard as a readable value such as `306ms` or `1.2s`.

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

The admin dashboard provides system-level monitoring:

- Active alerts
- Today’s cases
- Average model detection time
- Alert statistics and recent events

### 🚑 Responder Dashboard

The responder dashboard focuses on active response work:

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

## 🔐 Basic Security Note

- Passwords are hashed before storage.
- Sensitive values should not be displayed in frontend pages.
- Confidence values are used internally and hidden from users.

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

