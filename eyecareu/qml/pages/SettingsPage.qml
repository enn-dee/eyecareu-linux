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

        Card {
            title: "Startup"
            Layout.fillWidth: true
            ToggleRow {
                label: "Start Eye-CareU at login"
                checked: core.autostartEnabled
                onActivated: core.autostartEnabled = value
            }
            ToggleRow {
                label: "Start minimised to the tray"
                checked: core.startMinimised
                onActivated: core.startMinimised = value
            }
            ToggleRow {
                label: "Closing the window keeps it in the tray"
                checked: core.closeToTray
                onActivated: core.closeToTray = value
            }
        }

        Card {
            title: "Appearance"
            Layout.fillWidth: true
            ToggleRow {
                label: "Dark theme"
                checked: Theme.dark
                onActivated: Theme.dark = value
            }
        }

        Card {
            title: "Privacy"
            Layout.fillWidth: true
            ToggleRow {
                label: "Send anonymous usage statistics"
                description: "The Windows build used Google Analytics and Matomo. "
                             + "This port defaults to off and never enables it automatically."
                checked: core.telemetry
                onActivated: core.telemetry = value
            }
        }

        Card {
            title: "System"
            Layout.fillWidth: true
            GridLayout {
                columns: 2
                columnSpacing: Theme.gap
                rowSpacing: 6
                Layout.fillWidth: true
                Text { text: "Session"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text { text: core.sessionType; color: Theme.text; font.pixelSize: Theme.fontSmall }
                Text { text: "DDC/CI backend"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text { text: core.backendName; color: Theme.text; font.pixelSize: Theme.fontSmall }
                Text { text: "Colour control"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text {
                    text: core.effectsMode === "hyprsunset"
                          ? "Hyprland (hyprsunset)"
                          : (core.effectsMode === "gamma" ? "X11 gamma ramp"
                             : (core.effectsMode === "overlay" ? "overlay (limited)" : "unavailable"))
                    color: core.effectsMode === "overlay" ? Theme.warn : Theme.accent
                    font.pixelSize: Theme.fontSmall
                }
                Text { text: "Detected displays"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text { text: String(core.monitors.length); color: Theme.text; font.pixelSize: Theme.fontSmall }
            }
            Button {
                text: "Refresh displays"
                onClicked: core.refreshMonitors()
            }
        }

        Card {
            title: "About"
            Layout.fillWidth: true
            Text {
                text: appName + " " + appVersion
                color: Theme.text
                font.pixelSize: Theme.fontBase
                font.bold: true
            }
            Text {
                text: "A Linux port of the BenQ Eye-CareU Windows application "
                      + "(version " + sourceVersion + "). "
                      + "DDC/CI control, software eye-care effects, timers, reminders and "
                      + "the screen-time report are reimplemented natively."
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}
