import javax.inject.Inject

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.cursedentertainment.rift"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.cursedentertainment.rift"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20231013")   // Android's org.json is a stub off-device
}

// ── The dashboard: RIFT's own templates/, static/ and colour_scheme.xml ──────────
// Copied into the APK's assets at every build, so the phone serves exactly what
// app.py serves: no hand copies to drift. Edit them in RIFT, rebuild the app.
abstract class CopyDashboard @Inject constructor(private val fs: FileSystemOperations) : DefaultTask() {
    @get:InputDirectory abstract val templates: DirectoryProperty
    @get:InputDirectory abstract val staticDir: DirectoryProperty
    @get:InputFile abstract val colours: RegularFileProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun copy() {
        fs.sync {
            into(outputDir)
            from(templates) { into("templates") }
            from(staticDir) { into("static") }
            from(colours)
        }
    }
}

val riftRoot = rootProject.layout.projectDirectory.dir("..")   // RIFT/ (this project is RIFT/Android App)
val copyDashboard = tasks.register<CopyDashboard>("copyDashboard") {
    templates.set(riftRoot.dir("templates"))
    staticDir.set(riftRoot.dir("static"))
    colours.set(riftRoot.file("colour_scheme.xml"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyDashboard, CopyDashboard::outputDir)
    }
}

// ── Colours and icon: RIFT's colour_scheme.xml and images/rift_avatar.jpg ────────
// Turned into res/values/rift_colours.xml (@color/rift_background, rift_accent, ...)
// and res/drawable-nodpi/rift_avatar.jpg, the launcher icon's picture (the launcher
// crops it to its own shape: res/mipmap-anydpi-v26/), at build time like the dashboard.
abstract class GenerateRiftRes @Inject constructor(private val fs: FileSystemOperations) : DefaultTask() {
    @get:InputFile abstract val colours: RegularFileProperty
    @get:InputFile abstract val avatar: RegularFileProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun generate() {
        val out = outputDir.get().asFile
        fs.delete { delete(out) }
        val pairs = Regex("""name="(\w+)"\s+value="(#[0-9A-Fa-f]{6})"""").findAll(colours.get().asFile.readText())
        File(out, "values").apply { mkdirs() }.resolve("rift_colours.xml").writeText(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<!-- Generated from RIFT's colour_scheme.xml: edit that, not this. -->\n<resources>\n" +
                pairs.joinToString("") { "    <color name=\"rift_${it.groupValues[1]}\">${it.groupValues[2]}</color>\n" } +
                "</resources>\n")
        fs.copy {
            from(avatar)
            into(File(out, "drawable-nodpi"))
            rename { "rift_avatar.jpg" }
        }
    }
}

val generateRiftRes = tasks.register<GenerateRiftRes>("generateRiftRes") {
    colours.set(riftRoot.file("colour_scheme.xml"))
    avatar.set(riftRoot.file("images/rift_avatar.jpg"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.res?.addGeneratedSourceDirectory(generateRiftRes, GenerateRiftRes::outputDir)
    }
}
