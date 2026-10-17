import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: root

    property string label: ""
    property string suffix: ""
    property string display: ""
    property real value: 0
    property real from: 0
    property real to: 100
    property real stepSize: 1
    property bool enabledControl: true
    signal moved(real value)

    Layout.fillWidth: true

    RowLayout {
        Layout.fillWidth: true
        Text {
            text: root.label
            color: root.enabledControl ? Theme.text : Theme.textDim
            font.pixelSize: Theme.fontBase
            Layout.fillWidth: true
        }
        Text {
            text: root.display.length > 0 ? root.display
                  : (Math.round(slider.value) + root.suffix)
            color: Theme.textDim
            font.pixelSize: Theme.fontBase
        }
    }

    Slider {
        id: slider
        Layout.fillWidth: true
        enabled: root.enabledControl
        from: root.from
        to: root.to
        stepSize: root.stepSize
        Binding on value {
            value: root.value
            restoreMode: Binding.RestoreBindingOrValue
        }
        onMoved: root.moved(value)
    }
}
