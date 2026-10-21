import os
import re
import shutil
import subprocess
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

# ---------- Helper Functions ----------
def sanitize_package(url):
    domain = re.sub(r'^https?://', '', url).split('/')[0]
    domain = re.sub(r'[^a-zA-Z0-9]', '', domain) or "myapp"
    return f"com.webview.{domain.lower()}"

def create_webview_project(url, app_name, out_dir):
    pkg = sanitize_package(url)
    pkg_path = pkg.replace('.', '/')
    p = Path(out_dir)
    if p.exists():
        shutil.rmtree(p)

    (p / "app/src/main/java" / pkg_path).mkdir(parents=True)
    (p / "app/src/main/res/values").mkdir(parents=True)

    # MainActivity.java
    (p / "app/src/main/java" / pkg_path / "MainActivity.java").write_text(f'''package {pkg};

import android.os.Bundle;
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
        webView.setWebViewClient(new WebViewClient());
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

    (p / "app/src/main/res/values/strings.xml").write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<resources>\n'
        f'    <string name="app_name">{app_name}</string>\n'
        f'    <string name="app_url">{url}</string>\n'
        f'</resources>\n')

    (p / "app/src/main/AndroidManifest.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{pkg}">
    <uses-permission android:name="android.permission.INTERNET"/>
    <application
        android:allowBackup="true"
        android:icon="@android:drawable/sym_def_app_icon"
        android:label="@string/app_name"
        android:usesCleartextTraffic="true"
        android:theme="@style/Theme.AppCompat.Light.NoActionBar">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>
''')

    (p / "app/build.gradle").write_text(f'''plugins {{ id 'com.android.application' }}
android {{
    namespace '{pkg}'
    compileSdk 34
    defaultConfig {{
        applicationId '{pkg}'
        minSdk 21
        targetSdk 34
        versionCode 1
        versionName "1.0"
    }}
    compileOptions {{
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }}
}}
dependencies {{
    implementation 'androidx.appcompat:appcompat:1.6.1'
}}
''')

    (p / "build.gradle").write_text(
        "plugins { id 'com.android.application' version '8.2.0' apply false }\n")

    (p / "settings.gradle").write_text('''pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositories { google(); mavenCentral() }
}
rootProject.name = "WebViewApp"
include ':app'
''')

    (p / "gradle.properties").write_text(
        "org.gradle.jvmargs=-Xmx2048m\nandroid.useAndroidX=true\n")

    return p

def build_apk(project_dir):
    # Heroku par gradle build chalane ki koshish
    result = subprocess.run(
        ["gradle", "assembleDebug"],
        cwd=project_dir,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Build failed:\n{result.stderr}")
    apk_path = Path(project_dir) / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk_path.exists():
        raise RuntimeError("APK file not generated.")
    return apk_path

# ---------- Flask Routes ----------
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>URL to APK Converter</title>
    <style>
        body { font-family: Arial; max-width: 600px; margin: 40px auto; padding: 20px; }
        input[type=text] { width: 100%; padding: 10px; margin: 10px 0; }
        input[type=submit] { background: #007bff; color: white; padding: 10px 20px; border: none; cursor: pointer; }
        .flash { color: red; }
    </style>
</head>
<body>
    <h2>Website URL to Android APK</h2>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <ul class="flash">
        {% for msg in messages %}
          <li>{{ msg }}</li>
        {% endfor %}
        </ul>
      {% endif %}
    {% endwith %}
    <form method="POST" action="/">
        <label>Website URL:</label>
        <input type="text" name="url" placeholder="https://example.com" required>
        <label>App Name (optional):</label>
        <input type="text" name="app_name" placeholder="My App">
        <input type="submit" value="Build APK">
    </form>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        app_name = request.form.get("app_name", "").strip() or "My WebView App"

        if not url.startswith(("http://", "https://")):
            flash("URL must start with http:// or https://")
            return redirect(url_for("index"))

        try:
            # Heroku ke /tmp me project banayenge
            project_dir = "/tmp/webview_project"
            create_webview_project(url, app_name, project_dir)
            apk_path = build_apk(project_dir)

            # APK ko /tmp me copy karke send karenge
            final_apk = f"/tmp/{app_name.replace(' ', '_')}.apk"
            shutil.copy(apk_path, final_apk)

            return send_file(final_apk, as_attachment=True, download_name=f"{app_name}.apk")
        except Exception as e:
            flash(f"Error: {str(e)}")
            return redirect(url_for("index"))

    return render_template_string(TEMPLATE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
