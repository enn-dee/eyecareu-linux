import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    anchors.fill: parent
    z: 100
    visible: core.breakOverlayVisible
    color: Qt.rgba(0, 0, 0, 0.74)

    function formatTime(seconds) {
        var s = Math.max(0, Math.round(seconds))
        var m = Math.floor(s / 60)
        var r = s % 60
        return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r
    }

    MouseArea { anchors.fill: parent }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: Theme.pad * 1.5

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: core.breakOverlayKind === "twenty"
                  ? "Look 20 feet away"
                  : (core.breakOverlayTitle || "Take a break")
            color: "#ffffff"
            font.pixelSize: 30
            font.bold: true
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: root.formatTime(core.breakOverlayRemaining)
            color: Theme.accent
            font.pixelSize: 72
            font.bold: true
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "Relax your eyes and blink a few times."
            color: "#d8d8d8"
            font.pixelSize: Theme.fontBase
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.gap

            Button {
                text: "Skip break"
                highlighted: true
                onClicked: {
                    if (core.breakOverlayKind === "twenty") core.skipTwenty()
                    else core.skipPomodoro()
                    core.dismissOverlay()
                }
            }
            Button {
                text: "Dismiss"
                onClicked: core.dismissOverlay()
            }
        }
    }
}
