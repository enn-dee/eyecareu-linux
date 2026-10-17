import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: root

    property string label: ""
    property string description: ""
    property bool checked: false
    property bool compact: false
    signal activated(bool value)

    Layout.fillWidth: true

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text {
            text: root.label
            color: Theme.text
            font.pixelSize: Theme.fontBase
            Layout.fillWidth: true
        }
        Text {
            visible: root.description.length > 0
            text: root.description
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    Switch {
        id: control
        Binding on checked {
            value: root.checked
            restoreMode: Binding.RestoreBindingOrValue
        }
        onToggled: root.activated(checked)
    }
}
