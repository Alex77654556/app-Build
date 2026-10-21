import os
import re
import shutil
import subprocess
import threading
import uuid
import requests
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

tasks = {}

def sanitize_package(url):
    domain = re.sub(r'^https?://', '', url).split('/')[0]
    domain = re.sub(r'[^a-zA-Z0-9]', '', domain) or "myapp"
    return f"com.webview.{domain.lower()}"

def create_webview_project(url, app_name, icon_url, out_dir):
    pkg = sanitize_package(url)
    pkg_path = pkg.replace('.', '/')
    p = Path(out_dir)
    if p.exists(): shutil.rmtree(p)

    (p / "app/src/main/java" / pkg_path).mkdir(parents=True)
    (p / "app/src/main/res/values").mkdir(parents=True)
    (p / "app/src/main/res/drawable").mkdir(parents=True)

    # Logo Download Logic
    icon_reference = "@android:drawable/sym_def_app_icon"
    if icon_url:
        try:
            response = requests.get(icon_url, stream=True)
            if response.status_code == 200:
                with open(p / "app/src/main/res/drawable/app_logo.png", 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                icon_reference = "@drawable/app_logo"
        except Exception as e:
            print(f"Logo download failed: {e}")

    # MainActivity.java with PDF & New Tab handling
    (p / "app/src/main/java" / pkg_path / "MainActivity.java").write_text(f'''package {pkg};
import android.os.Bundle;
import android.os.Message;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {{
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        
        webView.setWebViewClient(new WebViewClient() {{
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {{
                String url = request.getUrl().toString();
                if (url.endsWith(".pdf") || url.contains(".pdf?")) {{
                    view.loadUrl("https://docs.google.com/gview?embedded=true&url=" + url);
                    return true;
                }}
                return false;
            }}
        }});

        webView.setWebChromeClient(new WebChromeClient() {{
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {{
                WebView newWebView = new WebView(view.getContext());
                newWebView.setWebViewClient(new WebViewClient() {{
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView view, String url) {{
                        if (url.endsWith(".pdf") || url.contains(".pdf?")) {{
                            view.loadUrl("https://docs.google.com/gview?embedded=true&url=" + url);
                        }} else {{
                            view.loadUrl(url);
                        }}
                        return true;
                    }}
                }});
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(newWebView);
                resultMsg.sendToTarget();
                return true;
            }}
        }});

        webView.loadUrl(getString(R.string.app_url));
        setContentView(webView);
    }}

    @Override
    public void onBackPressed() {{
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }}
}}
''')

    (p / "app/src/main/res/values/strings.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
    <string name="app_url">{url}</string>
</resources>''')

    (p / "app/src/main/AndroidManifest.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{pkg}">
    <uses-permission android:name="android.permission.INTERNET"/>
    <application android:allowBackup="true" android:icon="{icon_reference}"
        android:label="@string/app_name" android:usesCleartextTraffic="true"
        android:theme="@style/Theme.AppCompat.Light.NoActionBar">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>''')

    (p / "app/build.gradle").write_text(f'''plugins {{ id 'com.android.application' }}
android {{
    namespace '{pkg}'
    compileSdk 34
    defaultConfig {{ applicationId '{pkg}'; minSdk 21; targetSdk 34; versionCode 1; versionName "1.0" }}
    compileOptions {{ sourceCompatibility JavaVersion.VERSION_17; targetCompatibility JavaVersion.VERSION_17 }}
}}
dependencies {{ implementation 'androidx.appcompat:appcompat:1.6.1' }}''')

    (p / "build.gradle").write_text("plugins { id 'com.android.application' version '8.2.0' apply false }\n")
    (p / "settings.gradle").write_text('''pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = "WebViewApp"
include ':app'
''')
    (p / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\nandroid.useAndroidX=true\n")

def build_apk_thread(task_id, url, app_name, icon_url):
    try:
        project_dir = f"/tmp/webview_{task_id}"
        create_webview_project(url, app_name, icon_url, project_dir)
        
        env = os.environ.copy()
        result = subprocess.run(
            ["gradle", "assembleDebug", "--no-daemon"], 
            cwd=project_dir, 
            capture_output=True, 
            text=True,
            env=env
        )
        
        if result.returncode != 0:
            tasks[task_id] = {"status": "error", "message": result.stderr[-1000:]}
            return
            
        apk_path = Path(project_dir) / "app/build/outputs/apk/debug/app-debug.apk"
        final_apk = f"/tmp/{task_id}.apk"
        shutil.copy(apk_path, final_apk)
        
        tasks[task_id] = {"status": "success", "file": final_apk}
    except Exception as e:
        tasks[task_id] = {"status": "error", "message": str(e)}

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>Dashboard - App Builder</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body { margin: 0; font-family: 'Inter', sans-serif; background-color: #F4F5F1; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
        .container { background: #ffffff; padding: 40px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); width: 100%; max-width: 400px; text-align: center; }
        .logo-svg { width: 70px; margin-bottom: 20px; }
        .spinner { width: 70px; animation: _il_spin 1.5s ease-in-out infinite; display: none; margin: 0 auto; }
        @keyframes _il_spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        h2 { margin-top: 0; color: #1E8A7A; }
        p { color: #666; font-size: 14px; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; font-family: 'Inter', sans-serif; background: #FAFAFA; }
        button { width: 100%; padding: 14px; background: #1E8A7A; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 10px; transition: background 0.3s; }
        button:hover { background: #3CB989; }
        #error-msg { color: #e74c3c; background: #fadbd8; padding: 10px; border-radius: 8px; margin-top: 15px; font-size: 12px; word-break: break-all; display: none; text-align: left;}
        .download-btn { background: #3CB989; text-decoration: none; display: block; padding: 14px; color: white; border-radius: 8px; font-weight: 600; margin-top: 20px; }
    </style>
</head>
<body>
<div class="container">
    <svg id="app-logo" class="logo-svg" viewBox="0 0 32 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M5.125 4.44067H10.5641L16.0033 13.8681H11.0091L5.125 4.44067Z" fill="#5ED9A6"/>
        <path d="M10.5645 4.44279L13.2882 -0.267822L18.5038 9.53837L16.0036 13.8661L10.5645 4.44072V4.44279Z" fill="#3CB989"/>
        <path d="M7.24655 0.764961L5.12305 4.44073H10.5622L13.2859 -0.267814H9.04097C8.30209 -0.269884 7.61702 0.125427 7.24862 0.764961H7.24655Z" fill="#1E8A7A"/>
        <path d="M16.001 13.866H26.8813L29.603 9.15747L18.5012 9.53829L16.001 13.866Z" fill="#3CB989"/>
        <path d="M26.882 13.8703L29.5995 18.583L31.723 14.9072C32.0934 14.2677 32.0934 13.4791 31.723 12.8375L29.6015 9.15967L26.8799 13.8703H26.882Z" fill="#1E8A7A"/>
        <path d="M16.001 13.866L18.4991 18.1937L29.5988 18.5807L26.8813 13.868H16.001V13.866Z" fill="#5ED9A6"/>
        <path d="M16.0007 13.866L10.5574 23.2851H5.11621L11.0065 13.866H16.0007Z" fill="#3CB989"/>
        <path d="M10.5576 23.2873L13.2751 28L18.499 18.1959L16.0009 13.8682L10.5576 23.2873Z" fill="#1E8A7A"/>
        <path d="M5.11621 23.2852L7.23764 26.963C7.60812 27.6025 8.29112 27.9978 9.02999 27.9978H13.277L10.5595 23.2872H5.11828L5.11621 23.2852Z" fill="#5ED9A6"/>
    </svg>
    <svg id="spinner" class="spinner" viewBox="0 0 32 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M5.125 4.44067H10.5641L16.0033 13.8681H11.0091L5.125 4.44067Z" fill="#5ED9A6"/>
        <path d="M10.5645 4.44279L13.2882 -0.267822L18.5038 9.53837L16.0036 13.8661L10.5645 4.44072V4.44279Z" fill="#3CB989"/>
        <path d="M7.24655 0.764961L5.12305 4.44073H10.5622L13.2859 -0.267814H9.04097C8.30209 -0.269884 7.61702 0.125427 7.24862 0.764961H7.24655Z" fill="#1E8A7A"/>
        <path d="M16.001 13.866H26.8813L29.603 9.15747L18.5012 9.53829L16.001 13.866Z" fill="#3CB989"/>
        <path d="M26.882 13.8703L29.5995 18.583L31.723 14.9072C32.0934 14.2677 32.0934 13.4791 31.723 12.8375L29.6015 9.15967L26.8799 13.8703H26.882Z" fill="#1E8A7A"/>
        <path d="M16.001 13.866L18.4991 18.1937L29.5988 18.5807L26.8813 13.868H16.001V13.866Z" fill="#5ED9A6"/>
        <path d="M16.0007 13.866L10.5574 23.2851H5.11621L11.0065 13.866H16.0007Z" fill="#3CB989"/>
        <path d="M10.5576 23.2873L13.2751 28L18.499 18.1959L16.0009 13.8682L10.5576 23.2873Z" fill="#1E8A7A"/>
        <path d="M5.11621 23.2852L7.23764 26.963C7.60812 27.6025 8.29112 27.9978 9.02999 27.9978H13.277L10.5595 23.2872H5.11828L5.11621 23.2852Z" fill="#5ED9A6"/>
    </svg>

    <h2 id="title">Website to APK</h2>
    <p id="subtitle">Convert any URL into an Android App</p>

    <form id="build-form">
        <input type="url" id="url" placeholder="Website URL (https://...)" required>
        <input type="text" id="app_name" placeholder="App Name (e.g. Testbook)">
        <input type="url" id="icon_url" placeholder="Logo URL (Optional .png)">
        <button type="submit" id="build-btn">Build App</button>
    </form>

    <div id="error-msg"></div>
    <div id="success-area"></div>
</div>

<script>
    const form = document.getElementById('build-form');
    const spinner = document.getElementById('spinner');
    const logo = document.getElementById('app-logo');
    const title = document.getElementById('title');
    const subtitle = document.getElementById('subtitle');
    const errorMsg = document.getElementById('error-msg');
    const successArea = document.getElementById('success-area');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        form.style.display = 'none';
        errorMsg.style.display = 'none';
        logo.style.display = 'none';
        spinner.style.display = 'block';
        title.innerText = "Building APK...";
        subtitle.innerText = "Please wait 2-4 minutes. Do not close.";

        const url = document.getElementById('url').value;
        const app_name = document.getElementById('app_name').value || "MyApp";
        const icon_url = document.getElementById('icon_url').value || "";

        try {
            const response = await fetch('/api/build', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: url, app_name: app_name, icon_url: icon_url})
            });
            const data = await response.json();
            
            if (data.task_id) {
                checkStatus(data.task_id);
            } else {
                showError(data.error || "Failed to start.");
            }
        } catch (err) {
            showError("Server connection failed.");
        }
    });

    async function checkStatus(taskId) {
        try {
            const res = await fetch('/api/status/' + taskId);
            const data = await res.json();

            if (data.status === 'building') {
                setTimeout(() => checkStatus(taskId), 5000); 
            } else if (data.status === 'success') {
                spinner.style.display = 'none';
                title.innerText = "App Ready!";
                subtitle.innerText = "Your APK has been generated.";
                successArea.innerHTML = `<a href="/download/${taskId}" class="download-btn">Download APK</a>`;
            } else {
                showError(data.message || "Build failed. Check logs.");
            }
        } catch (err) {
            showError("Error checking status.");
        }
    }

    function showError(msg) {
        spinner.style.display = 'none';
        logo.style.display = 'block';
        title.innerText = "Build Failed";
        subtitle.innerText = "Something went wrong.";
        form.style.display = 'block';
        errorMsg.innerText = msg;
        errorMsg.style.display = 'block';
    }
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/build", methods=["POST"])
def api_build():
    data = request.json
    url = data.get("url", "").strip()
    app_name = data.get("app_name", "").strip() or "MyApp"
    icon_url = data.get("icon_url", "").strip()

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL must start with http:// or https://"})

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "building"}
    
    thread = threading.Thread(target=build_apk_thread, args=(task_id, url, app_name, icon_url))
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route("/api/status/<task_id>")
def api_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "message": "Task not found"}), 404
    return jsonify(task)

@app.route("/download/<task_id>")
def download(task_id):
    task = tasks.get(task_id)
    if task and task["status"] == "success":
        return send_file(task["file"], as_attachment=True, download_name="App.apk")
    return "File not found", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
