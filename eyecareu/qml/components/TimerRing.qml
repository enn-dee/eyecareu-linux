import QtQuick
import "../theme"

Item {
    id: root

    property real progress: 0
    property string centerText: ""
    property string caption: ""
    property color ringColor: Theme.accent
    property int thickness: 10

    implicitWidth: 170
    implicitHeight: 170

    onProgressChanged: canvas.requestPaint()
    onRingColorChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var cx = width / 2
            var cy = height / 2
            var r = Math.min(width, height) / 2 - root.thickness
            ctx.lineWidth = root.thickness
            ctx.lineCap = "round"

            ctx.strokeStyle = Theme.border.toString()
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, Math.PI * 2)
            ctx.stroke()

            var p = Math.max(0, Math.min(1, root.progress))
            if (p > 0) {
                ctx.strokeStyle = root.ringColor.toString()
                ctx.beginPath()
                ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * p)
                ctx.stroke()
            }
        }
    }

    Component.onCompleted: canvas.requestPaint()

    Column {
        anchors.centerIn: parent
        spacing: 2
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.centerText
            color: Theme.text
            font.pixelSize: 30
            font.bold: true
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.caption.length > 0
            text: root.caption
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
    }
}
