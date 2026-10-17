import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    property string title: ""
    property string message: ""
    property string kind: ""

    width: Math.min(parent.width - 40, 460)
    height: content.implicitHeight + 24
    radius: Theme.radius
    color: Theme.surface
    border.color: Theme.border
    border.width: 1
    visible: false
    z: 90

    function show(k, t, m) {
        root.kind = k
        root.title = t
        root.message = m
        root.visible = true
        hideTimer.restart()
    }

    Timer {
        id: hideTimer
        interval: 12000
        onTriggered: root.visible = false
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: 12
        spacing: 6

        Text {
            text: root.title
            color: Theme.text
            font.pixelSize: Theme.fontBase
            font.bold: true
            Layout.fillWidth: true
        }
        Text {
            text: root.message
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        RowLayout {
            spacing: 8
            Button {
                text: "Snooze 10 min"
                onClicked: {
                    core.snoozeReminder(root.kind)
                    root.visible = false
                }
            }
            Button {
                text: "Dismiss"
                onClicked: root.visible = false
            }
        }
    }
}
