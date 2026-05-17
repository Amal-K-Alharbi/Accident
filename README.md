# AcciVision - Traffic Accident Detection System

AcciVision is a Flask web application for detecting traffic accidents from uploaded video files or a browser camera feed. It uses a custom YOLOv8 model to analyze frames, save accident snapshots, and route alerts through an admin and responder workflow.

## Project Overview

The system provides a browser-based command center for accident detection and alert handling. Admin users can run the model on video sources, review detected incidents, and send valid alerts to responders. Responder users can view dispatched alerts, inspect evidence, update response progress, and resolve incidents.

The current project is built as a single Flask application in `app.py`, with HTML templates in `templates/`, styling and saved accident images in `static/`, uploaded video storage in `uploads/`, and SQLite data stored in `accivision.db`.

## Main Purpose

The main purpose of AcciVision is to reduce manual monitoring work by using computer vision to detect possible road accidents and create a simple alert workflow from detection to response.

## Key Features

| Feature | Description |
| --- | --- |
| Public intro page | Shows the AcciVision landing page before login. |
| Authentication | Supports sign up, login, logout, sessions, and password hashing with Werkzeug. |
| Role selection | Users register as either Admin / Operator or Responder. |
| Admin dashboard | Shows active alerts, camera count, today events, average model detection time, and recent events. |
| Video upload detection | Admin can upload MP4, AVI, MOV, MKV, WMV, or WebM files up to 200 MB. |
| Browser camera detection | Admin can open the local browser camera and send frames for detection. |
| YOLOv8 inference | Uses `best.pt` and labels from `coco.txt` to detect `accident` and `cars`. |
| Accident snapshots | Saves detected accident images in `static/accidents/`. |
| Audio warning | Plays `static/assets/warning.mp3` when an accident is detected. |
| Admin alert review | Admin can approve alerts and send them to responders, or mark new alerts as false alarms. |
| Responder dashboard | Shows assigned alerts and status counts. |
| Responder detail page | Responders can view accident images/videos and update response status. |
| SQLite persistence | Stores users, accident records, status fields, timing data, confidence, and source video name. |

## User Roles and Workflow

| Role | Main Pages | Main Actions |
| --- | --- | --- |
| Admin / Operator | Dashboard, Alerts, Test Model | Upload video, run camera detection, review incidents, approve and send alerts, mark false alarms, monitor status. |
| Responder | Responder Dashboard, Responder Alerts, Alert Details | View assigned cases, inspect saved evidence, update response status, resolve cases. |

### Typical Flow

1. A user opens the app and logs in or chooses a role to register.
2. An admin goes to **Test Model**.
3. The admin uploads a supported video file or starts browser camera detection.
4. The YOLOv8 model processes frames and draws detection boxes.
5. If an accident is confirmed, the app saves a snapshot and creates an accident record.
6. Confirmed accidents below the auto-dispatch threshold appear as new admin review alerts.
7. High-confidence confirmed accidents are sent directly to the responder workflow.
8. The admin can approve new alerts or mark them as false alarms.
9. Responders view dispatched alerts and update progress.
10. Responders mark the case as resolved when complete.

## Technologies Used

| Layer | Technology |
| --- | --- |
| Backend | Python, Flask |
| AI / Detection | Ultralytics YOLOv8, custom `best.pt` model |
| Computer Vision | OpenCV, NumPy |
| Data | SQLite |
| Frontend | HTML, CSS, JavaScript, Jinja templates |
| Authentication | Flask sessions, Werkzeug password hashing |
| Media | Multipart JPEG streams, browser camera frame uploads, saved JPEG snapshots |

Dependencies are listed in `requirements.txt`:

```text
flask
opencv-python
pandas
ultralytics
numpy
```

## Project Structure

```text
accident_web/
|-- app.py                         # Main Flask app, routes, database logic, detection pipeline
|-- accivision.db                  # SQLite database used by the app
|-- best.pt                        # Custom YOLOv8 model file
|-- coco.txt                       # Class labels: accident, cars
|-- requirements.txt               # Python dependencies
|-- README.md                      # Project documentation
|-- cloudflared-windows-amd64.exe  # Bundled Cloudflare tunnel executable
|
|-- templates/
|   |-- intro.html                 # Public landing page
|   |-- login.html                 # Login and registration form
|   |-- select_role.html           # Role selection page
|   |-- sidebar.html               # Shared authenticated navigation
|   |-- home.html                  # Dashboard
|   |-- detect.html                # Admin detection workspace
|   |-- alerts.html                # Admin alert review page
|   |-- respond.html               # Responder dashboard
|   `-- responder_alert.html       # Responder list/detail page
|
|-- static/
|   |-- css/
|   |   `-- style.css              # Application styling
|   |-- assets/
|   |   `-- warning.mp3            # Browser warning sound
|   `-- accidents/
|       `-- accident_*.jpg         # Saved accident snapshots
|
`-- uploads/
    `-- video files                # Uploaded videos while detection is running
```

## Routes and Pages

| Route | Access | Purpose |
| --- | --- | --- |
| `/` and `/intro.html` | Public | Intro page. |
| `/login` and `/login.html` | Public | Login and sign-up form. |
| `/select-role` and `/select_role.html` | Public | Choose Admin or Responder before registration. |
| `/register/admin` | Public | Starts admin registration. |
| `/register/responder` | Public | Starts responder registration. |
| `/logout` | Logged in | Clears session and returns to intro page. |
| `/dashboard`, `/home.html` | Admin | Admin dashboard. |
| `/home` | Logged in | Redirects the user to the correct dashboard for their role. |
| `/detect`, `/detect.html` | Admin | Video upload and camera detection workspace. |
| `/alerts`, `/alerts.html` | Admin | Alert review and dispatch page. |
| `/responder` | Responder | Responder dashboard. |
| `/responder/alerts`, `/responder_alert.html` | Responder | Responder alert list. |
| `/responder/alert/<accident_id>` | Responder | Alert detail and status update page. |
| `/upload` | Admin | Uploads a video file. |
| `/video_feed` | Admin | Streams processed uploaded-video frames. |
| `/process_camera_frame` | Admin | Processes one browser camera frame. |
| `/camera_feed` | Admin | Streams server-side camera frames from camera index 0. |
| `/accident_status` | Admin | Polled by the browser to trigger warning sound. |
| `/report_alert/<accident_id>` | Admin | Sends an alert to responders. |
| `/false_alarm/<accident_id>` | Admin | Marks a new alert as false alarm. |
| `/responder/update-status` | Responder | Updates responder status. |

## Database

The database is SQLite and is opened through `get_db()` in `app.py`. The app creates or migrates tables at startup using `init_db()`.

### `users`

| Column | Purpose |
| --- | --- |
| `id` | User ID. |
| `email` | Unique login email. |
| `password` | Hashed password. Older plain/SHA-256 values can be upgraded after successful login. |
| `role` | `admin` or `responder`. |
| `created_at` | Creation timestamp. |

### `accidents`

| Column | Purpose |
| --- | --- |
| `id` | Short UUID-based accident ID. |
| `image` | Saved accident snapshot filename. |
| `timestamp` | Detection time as Unix timestamp. |
| `notified` | Whether the alert was sent to responders. |
| `responded` | Whether a responder has acknowledged/progressed the alert. |
| `closed` | Whether the case is closed. |
| `status` | Main lifecycle status: `new`, `sent_to_responder`, `responded`, `closed`, or `false_alarm`. |
| `response_status` | Responder status: `pending`, `acknowledged`, `en_route`, `on_scene`, or `resolved`. |
| `sent_at`, `reported_at`, `responded_at`, `closed_at` | Alert workflow timestamps. |
| `detection_time_seconds` | Model inference time for saved detections. |
| `assigned_responder` | Responder email or default responder team label. |
| `confidence` | Accident confidence saved with the detection. |
| `source_video` | Uploaded video filename when the alert came from a video upload. |

## How the Accident Detection Model Works

The model is loaded once when `app.py` starts:

```python
model = YOLO(MODEL_PATH)
```

The label file `coco.txt` currently contains:

```text
accident
cars
```

Detection steps in the current code:

1. A frame is resized to `768 x 432`.
2. YOLO prediction runs with image size `512` and confidence threshold `0.45`.
3. The app reads bounding boxes, class IDs, confidence scores, and labels.
4. If a label is `accident` and confidence is greater than `0.70`, the frame gets a red accident box and can contribute to confirmation.
5. Other detections are drawn with green boxes.
6. The app keeps a confirmation counter and requires `5` consecutive confirmed accident frames.
7. A confirmed accident is considered reviewable if it passes the review threshold. Because accident confirmation only increments for accident boxes above `0.70`, current saved review alerts are practically above 70% confidence.
8. A confirmed accident is auto-dispatched if confidence is at least `0.80`; otherwise, it waits for admin review.
9. Detection time is stored for saved snapshots and shown as average model detection time on the dashboard.

Important constants in `app.py`:

| Constant | Value | Meaning |
| --- | --- | --- |
| `ACCIDENT_CONFIRM_FRAMES` | `5` | Number of confirmed frames required before creating an alert. |
| `ADMIN_REVIEW_CONFIDENCE_THRESHOLD` | `0.50` | Review threshold after confirmation; the current accident-box gate means saved review alerts are practically above 70%. |
| `AUTO_REPORT_CONFIDENCE_THRESHOLD` | `0.80` | Confidence required for automatic responder dispatch. |
| `FRAME_SKIP_INTERVAL` | `2` | Processes every second frame for video/camera stream loops. |
| `MAX_CONTENT_LENGTH` | `200 MB` | Maximum upload size. |

## Alert and Response Process

```text
Video or Camera Frame
        |
        v
YOLOv8 Prediction
        |
        v
Accident box above 70% confidence?
        |
        v
5 confirmed frames?
        |
        +-- No --> Continue monitoring
        |
        +-- Yes
             |
             +-- Confidence >= 80% --> Save snapshot and send to responder
             |
             +-- Confidence > 70% and < 80% --> Save snapshot for admin review
```

Admin review states:

| Admin Action | Result |
| --- | --- |
| Approve and Send | Sets the alert to `sent_to_responder`, marks it notified, assigns `Responder Team`, and makes it visible to responders. |
| False Alarm | Sets status to `false_alarm`; the record remains in the database but is hidden from the admin live list and responder queues. |

Responder states:

| Status | Meaning |
| --- | --- |
| `pending` | Alert is waiting for responder action. |
| `acknowledged` | Responder acknowledged the alert. |
| `en_route` | Responder is on the way. |
| `on_scene` | Responder arrived at the scene. |
| `resolved` | Case is closed. |

## How to Run the Project

1. Create and activate a virtual environment.

```bash
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Make sure these model files are present in the project root:

```text
best.pt
coco.txt
```

The app can create and migrate the SQLite database automatically, but it expects the model and label files to exist.

4. Run the Flask app.

```bash
python app.py
```

5. Open the app in a browser.

```text
http://127.0.0.1:5001
```

The app is configured in `app.py` to run with:

```python
app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False, threaded=True)
```

## Screenshots

Add screenshots of the running application here when preparing a report or presentation.

| Page | Suggested Screenshot |
| --- | --- |
| Intro | Public AcciVision landing page. |
| Login / Role Selection | User login and role registration flow. |
| Admin Dashboard | Metrics and recent events. |
| Test Model | Video upload or camera detection workspace. |
| Alert Management | Admin alert cards and approval actions. |
| Responder Dashboard | Assigned alerts and response status chart. |
| Responder Alert Details | Evidence preview and response status buttons. |

Example Markdown format:

```markdown
![Admin Dashboard](docs/screenshots/admin-dashboard.png)
```

## Notes and Limitations

- The app uses a hard-coded Flask secret key in `app.py`; this should be moved to an environment variable for production.
- SQLite is suitable for local development and demos, but a production deployment should use a stronger database setup.
- The dashboard camera count checks local camera indexes `0` to `3` and displays the result beside a hard-coded `/165` label in the template.
- Alert locations are generated by `build_fake_location()` from a fixed list, not from GPS or map data.
- Uploaded videos are deleted after processing or when stopped, while saved accident snapshots remain in `static/accidents/`.
- Snapshot saving is throttled to one saved snapshot every 30 seconds to reduce duplicates during sustained detections.
- The browser camera flow sends captured frames to `/process_camera_frame`; it depends on browser camera permission and device support.
- `/camera_feed` exists for server-side camera index `0`, but the current detection page mainly uses browser camera frame uploads.
- The app has role-based route protection, but it does not include advanced account management, password reset, audit logs, or external emergency-service integration.
- The YOLO model accuracy depends on the quality and training data of `best.pt`.

## Future Improvements

- Move secrets and configuration values into environment variables.
- Add production-ready database migrations and a managed database.
- Add real camera/source management instead of local camera probing only.
- Add real location metadata, maps, and GPS support.
- Add notification integrations such as SMS, email, dispatch APIs, or WebSocket alerts.
- Add audit logs for admin approvals, false alarms, and responder updates.
- Add model evaluation metrics and configurable detection thresholds.
- Add automated tests for authentication, role guards, alert transitions, and detection API responses.
- Add screenshot assets under a documented `docs/screenshots/` folder.
- Improve deployment documentation for local network, cloud, or tunnel-based access.
