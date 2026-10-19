// RIFT's Android hub: the phone runs the fleet hub (registry, dashboard, mDNS) as a
// foreground service. Open this folder in Android Studio, or: gradlew assembleDebug
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "RIFT"
include(":app")
