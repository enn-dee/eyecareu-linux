import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    default property alias content: inner.data
    property string title: ""
    property bool compact: false

    color: Theme.surface
    radius: Theme.radius
    border.color: Theme.border
    border.width: 1
    implicitHeight: column.implicitHeight + Theme.pad * 2
    implicitWidth: 320

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.pad
        spacing: Theme.gap

        Text {
            visible: root.title.length > 0
            text: root.title
            color: Theme.text
            font.pixelSize: Theme.fontTitle
            font.bold: true
            Layout.fillWidth: true
        }

        ColumnLayout {
            id: inner
            Layout.fillWidth: true
            spacing: Theme.gap
        }
    }
}
