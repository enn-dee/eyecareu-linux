import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    property string label: ""
    property string value: ""
    property string caption: ""
    property color accent: Theme.accent

    color: Theme.surface
    radius: Theme.radius
    border.color: Theme.border
    border.width: 1
    implicitHeight: content.implicitHeight + Theme.pad * 2
    implicitWidth: 150

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: 4
        Text {
            text: root.label
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            Layout.fillWidth: true
        }
        Text {
            text: root.value
            color: root.accent
            font.pixelSize: Theme.fontHuge
            font.bold: true
            Layout.fillWidth: true
        }
        Text {
            visible: root.caption.length > 0
            text: root.caption
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            Layout.fillWidth: true
        }
    }
}
