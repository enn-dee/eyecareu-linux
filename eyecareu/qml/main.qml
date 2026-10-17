import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "theme"
import "components"
import "pages"
import "popups"

ApplicationWindow {
    id: window

    width: 1040
    height: 700
    minimumWidth: 880
    minimumHeight: 560
    visible: true
    title: appName
    color: Theme.bg

    property int currentPage: 0
    property var navModel: [
        { label: "Home",       source: "pages/HomePage.qml" },
        { label: "Display",    source: "pages/DisplayPage.qml" },
        { label: "Eye care",   source: "pages/EffectsPage.qml" },
        { label: "Timers",     source: "pages/TimersPage.qml" },
        { label: "Reminders",  source: "pages/RemindersPage.qml" },
        { label: "Report",     source: "pages/ReportPage.qml" },
        { label: "Settings",   source: "pages/SettingsPage.qml" }
    ]

    header: ToolBar {
        background: Rectangle { color: Theme.surface; border.color: Theme.border; border.width: 0
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border } }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.pad
            anchors.rightMargin: Theme.pad
            spacing: Theme.gap

            Text {
                text: appName
                color: Theme.text
                font.pixelSize: Theme.fontTitle
                font.bold: true
            }
            Chip { text: "v" + appVersion }
            Item { Layout.fillWidth: true }
            Chip {
                visible: core.monitors.length > 0
                text: core.selectedMonitorName || "no display"
                tint: Theme.accentSoft
            }
            Chip {
                text: core.backendName + " • " + core.sessionType
                tint: Theme.surfaceAlt
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // -- navigation sidebar ------------------------------------------
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 208
            color: Theme.surface

            Rectangle {
                anchors.right: parent.right
                width: 1
                height: parent.height
                color: Theme.border
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.gap
                spacing: 4

                Repeater {
                    model: window.navModel
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 42
                        radius: Theme.radiusSmall
                        color: window.currentPage === index ? Theme.accentSoft
                                                            : (navMouse.containsMouse ? Theme.surfaceAlt : "transparent")
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            text: modelData.label
                            color: window.currentPage === index ? Theme.accent : Theme.text
                            font.pixelSize: Theme.fontBase
                            font.bold: window.currentPage === index
                        }
                        MouseArea {
                            id: navMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: window.currentPage = index
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                Text {
                    Layout.fillWidth: true
                    text: core.statusMessage
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.WordWrap
                    visible: core.statusMessage.length > 0
                }
            }
        }

        // -- page content ------------------------------------------------
        Loader {
            id: pageLoader
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: window.navModel[window.currentPage].source
        }
    }

    // -- reminder toast ---------------------------------------------------
    ReminderToast {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
    }

    Connections {
        target: core
        function onReminderTriggered(kind, title, message) {
            toast.show(kind, title, message)
        }
    }

    // -- break overlay ----------------------------------------------------
    BreakOverlay { }

    // -- software-effects overlay (Wayland / sessions without colour ramps)
    Window {
        id: screenOverlay
        visible: core.screenOverlayVisible
        flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput
               | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        color: "transparent"
        x: 0
        y: 0
        width: Screen.width
        height: Screen.height

        Rectangle {
            anchors.fill: parent
            color: core.screenOverlayColor
        }
    }

    onClosing: function (close) {
        if (core.closeToTray) {
            close.accepted = false
            window.hide()
        } else {
            core.shutdown()
        }
    }
}
