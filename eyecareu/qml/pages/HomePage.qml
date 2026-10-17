import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Flickable {
    id: page
    contentWidth: width
    contentHeight: column.implicitHeight + Theme.pad * 2
    clip: true

    ScrollBar.vertical: ScrollBar {}

    ColumnLayout {
        id: column
        x: Theme.pad
        y: Theme.pad
        width: page.width - Theme.pad * 2
        spacing: Theme.gap

        // -- greeting / summary ------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap

            StatCard {
                label: "Today"
                value: core.todayMinutes + " min"
                caption: core.goalPercent + "% of daily goal"
                Layout.fillWidth: true
            }
            StatCard {
                label: "Longest stretch"
                value: core.todayStretchMinutes + " min"
                caption: core.todayBreaks + " breaks taken"
                accent: Theme.warn
                Layout.fillWidth: true
            }
            StatCard {
                label: "This week"
                value: core.weekMinutes + " min"
                caption: "avg " + core.weekAverageMinutes + " min/day"
                accent: "#3f6fb5"
                Layout.fillWidth: true
            }
        }

        // -- quick controls ----------------------------------------------
        Card {
            title: "Quick controls"
            Layout.fillWidth: true

            ToggleRow {
                label: "Night light"
                description: "Warm the screen using the X11 colour ramp."
                checked: core.nightLightEnabled
                onActivated: core.nightLightEnabled = value
            }
            ToggleRow {
                label: "Low blue light"
                description: "Reduce the blue channel by " + core.lowBlueLightLevel + "%."
                checked: core.lowBlueLightEnabled
                onActivated: core.lowBlueLightEnabled = value
            }
            ToggleRow {
                label: "20-20-20 timer"
                description: "Every " + core.twentyWorkMinutes + " minutes, look away for 20 seconds."
                checked: core.twentyRunning
                onActivated: core.setTwentyEnabled(value)
            }
            ToggleRow {
                label: "Pomodoro timer"
                description: "Focus in 25 minute blocks with short breaks."
                checked: core.pomodoroRunning
                onActivated: core.setPomodoroEnabled(value)
            }
        }

        // -- timer status -------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap

            Card {
                title: "20-20-20"
                Layout.fillWidth: true
                RowLayout {
                    Layout.fillWidth: true
                    TimerRing {
                        progress: core.twentyProgress
                        centerText: page.formatTime(core.twentyRemaining)
                        caption: core.twentyPhase
                        ringColor: Theme.accent
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Text {
                            text: core.twentyRunning
                                  ? (core.twentyPaused ? "Paused" : "Running")
                                  : "Stopped"
                            color: Theme.text
                            font.pixelSize: Theme.fontTitle
                            font.bold: true
                        }
                        Text {
                            text: "Cycles completed: " + core.twentyCycles
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                        RowLayout {
                            spacing: 8
                            Button { text: core.twentyRunning ? "Pause" : "Start"; onClicked: core.toggleTwenty() }
                            Button { text: "Skip"; onClicked: core.skipTwenty(); enabled: core.twentyRunning }
                            Button { text: "Stop"; onClicked: core.stopTwenty(); enabled: core.twentyRunning }
                        }
                    }
                }
            }
        }

        // -- monitors -----------------------------------------------------
        Card {
            title: "Displays"
            Layout.fillWidth: true
            Repeater {
                model: core.monitors
                delegate: RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gap
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text { text: modelData.name; color: Theme.text; font.pixelSize: Theme.fontBase; font.bold: true }
                        Text {
                            text: modelData.connector + "  •  "
                                  + (modelData.online ? "DDC/CI online"
                                     : (modelData.backlight ? "backlight" : "DDC/CI offline"))
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                    Chip { text: modelData.isBenq ? "BenQ" : (modelData.manufacturer || "Display") }
                    Switch {
                        checked: core.selectedDisplayId === modelData.displayId
                        onClicked: core.selectedDisplayId = modelData.displayId
                    }
                }
            }
            Text {
                visible: core.monitors.length === 0
                text: "No displays detected."
                color: Theme.textDim
                font.pixelSize: Theme.fontBase
            }
        }
    }

    function formatTime(seconds) {
        var s = Math.max(0, Math.round(seconds))
        var m = Math.floor(s / 60)
        var r = s % 60
        return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r
    }
}
