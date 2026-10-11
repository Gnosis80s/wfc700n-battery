import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "gnosis.earbuds"
  ipcTarget: "gnosis.earbuds"

  property var state: ({ connected: false, levels: {} })
  readonly property string iconGlyph: "\uDB86\uDC4F" // md-earbuds (U+F184F)
  readonly property var levels: state && state.levels ? state.levels : ({})
  readonly property bool charging: {
    var l = levels.left
    var r = levels.right
    var s = levels.single
    return !!((l && (l[1] === 1 || l[1] === 3))
        || (r && (r[1] === 1 || r[1] === 3))
        || (s && (s[1] === 1 || s[1] === 3)))
  }
  readonly property string heroStatus: root.state.connected ? (root.charging ? "Charging" : "Connected") : "Not connected"

  readonly property var rows: {
    var out = []
    if (levels.left) out.push({ label: "LEFT", data: levels.left })
    if (levels.right) out.push({ label: "RIGHT", data: levels.right })
    if (levels.single && !levels.left && !levels.right) out.push({ label: "BUDS", data: levels.single })
    if (levels.case) out.push({ label: "CASE", data: levels.case })
    return out
  }

  function chargingLabel(ch) {
    if (ch === 0) return "Not charging"
    if (ch === 1) return "Charging"
    if (ch === 3) return "Charged"
    return "Unknown"
  }

  function parse(jsonText) {
    try {
      state = JSON.parse(jsonText)
    } catch (e) {
      state = { connected: false, levels: {} }
    }
  }

  function refresh() {
    if (proc.running) proc.running = false
    proc.running = true
  }

  onOpenedChanged: if (opened) refresh()

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: proc
    command: ["bash", "-lc", "/home/gnosis/Work/wfc700n-battery/status.py --json-full"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.parse(text)
    }
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.iconGlyph
    tooltipText: "WF-C700N " + root.heroStatus
    onPressed: function(b) {
      if (b === Qt.LeftButton) root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function() {}
      onActivateRequested: function() {}
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function() {}
    }

    Column {
      id: column
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      spacing: Style.space(14)

      Item {
        width: parent.width
        implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

        Text {
          id: heroIcon
          textFormat: Text.PlainText
          text: root.iconGlyph
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.display
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
        }

        Column {
          id: heroLabels
          anchors.left: heroIcon.right
          anchors.leftMargin: Style.space(14)
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)

          Text {
            text: "WF-C700N"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }

          Text {
            textFormat: Text.PlainText
            text: root.heroStatus.toUpperCase()
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.2
            elide: Text.ElideRight
            width: parent.width
          }
        }
      }

      PanelSeparator {
        visible: root.state.connected
        foreground: root.bar.foreground
      }

      Column {
        width: parent.width
        visible: root.state.connected
        spacing: Style.space(10)

        Repeater {
          model: root.rows
          delegate: Item {
            required property var modelData
            width: column.width
            implicitHeight: Math.max(rowIcon.implicitHeight, rowInfo.implicitHeight)
            height: implicitHeight

            Text {
              id: rowIcon
              textFormat: Text.PlainText
              text: root.iconGlyph
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.heading
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: rowInfo
              spacing: Style.space(1)
              anchors.left: rowIcon.right
              anchors.leftMargin: Style.space(10)
              anchors.right: rowPct.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter

              Text {
                textFormat: Text.PlainText
                text: modelData.label
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                textFormat: Text.PlainText
                text: root.chargingLabel(modelData.data[1])
                color: Qt.darker(root.bar.foreground, 1.5)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                width: parent.width
              }
            }

            Text {
              id: rowPct
              textFormat: Text.PlainText
              text: modelData.data[0] + "%"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }
      }

      Text {
        textFormat: Text.PlainText
        visible: !root.state.connected
        text: root.state.error === "not_connected" ? "Not connected to WF-C700N"
            : root.state.error === "no_data" ? "Connected, awaiting battery data"
            : "Disconnected or unreachable"
        color: Qt.darker(root.bar.foreground, 1.5)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
        width: parent.width
      }
    }
  }
}
