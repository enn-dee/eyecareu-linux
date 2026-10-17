import QtQuick
import "../theme"

Rectangle {
    id: root

    property string text: ""
    property color tint: Theme.accentSoft
    property color textColor: Theme.text

    color: tint
    radius: height / 2
    implicitWidth: label.implicitWidth + 20
    implicitHeight: label.implicitHeight + 8

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.textColor
        font.pixelSize: Theme.fontSmall
    }
}
