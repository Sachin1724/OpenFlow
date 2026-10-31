import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// The beta signing key lives outside the repo (see android/README.md); without it the release build is unsigned.
val signing = Properties().apply {
    val f = file(System.getenv("OPENFLOW_SIGNING") ?: "C:/Android/keys/signing.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "app.openflow"
    compileSdk = 34
    defaultConfig {
        applicationId = "app.openflow"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.1.1-beta"
        ndk { abiFilters += "arm64-v8a" }   // the speech runtime ships for 64-bit ARM phones only
    }
    signingConfigs {
        create("beta") {
            if (signing.containsKey("ks.file")) {
                storeFile = file(signing.getProperty("ks.file")); storePassword = signing.getProperty("ks.pass")
                keyAlias = signing.getProperty("ks.alias"); keyPassword = signing.getProperty("ks.pass")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (signing.containsKey("ks.file")) signingConfig = signingConfigs.getByName("beta")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.14" }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.19.2")
    implementation(platform("androidx.compose:compose-bom:2024.09.03"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.animation:animation")
    implementation("androidx.activity:activity-compose:1.9.2")
}
