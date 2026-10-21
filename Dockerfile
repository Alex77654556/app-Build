FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

RUN apt-get update && apt-get install -y \
    python3 python3-pip openjdk-17-jdk wget unzip git \
    && rm -rf /var/lib/apt/lists/*

# Gradle install
RUN wget https://services.gradle.org/distributions/gradle-8.2-bin.zip -P /tmp \
    && unzip -d /opt/gradle /tmp/gradle-8.2-bin.zip \
    && ln -s /opt/gradle/gradle-8.2/bin/gradle /usr/bin/gradle

# Android SDK install
RUN mkdir -p $ANDROID_HOME/cmdline-tools \
    && wget https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -P /tmp \
    && unzip -d $ANDROID_HOME/cmdline-tools /tmp/commandlinetools-linux-11076708_latest.zip \
    && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
    && yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses \
    && $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "platforms;android-34" "build-tools;34.0.0"

WORKDIR /app
COPY . .
RUN pip3 install -r requirements.txt

# Railway default port 8080 use karta hai
CMD ["gunicorn", "app:app", "--timeout", "300", "--bind", "0.0.0.0:8080"]
