import PyQt5.QtGui as QtGui
import qgis.core as QGisCore

from .layer import PixelisedVectorLayer


class PixelMeasureAction(QtGui.QAction):
    """Class representing the action to start the pixel measure.
    Used as a menu item and toolbar button.
    """

    def __init__(self, main, parent):
        """Initialisation.
        Parameters
        ----------
        main : PixelCalculator
            Instance of main class.
        parent : QtGui.QWidget
            Widget used as parent widget for the action.
        """
        self.main = main
        QtGui.QAction.__init__(self,
                               QtGui.QIcon(':/plugins/pixel_calculator/icon.png'),
                               'Bereken pixelwaarden',
                               parent)

        self.mapCanvas = self.main.iface.mapCanvas()
        self.mapCanvas.extentsChanged.connect(self.populateVisible)

        self.main.iface.currentLayerChanged.connect(self.populateApplicable)

        self.rasterLayer = None
        self.previousMapTool = None
        self.layer = None

        self.populateApplicable()

        self.setCheckable(True)
        self.triggered.connect(self.activate)

    def populateApplicable(self):
        active_layer = self.main.iface.activeLayer()
        if isinstance(active_layer, QGisCore.QgsRasterLayer) or active_layer == self.layer:
            self.rasterLayer = active_layer
        else:
            self.rasterLayer = None
        self.populateVisible()

    def populateVisible(self):
        """Show or hide the action based on the visibility of the raster layer.
        Only show the action in the toolbar if the corresponding raster layer
        is visible too.
        """
        if self.rasterLayer and \
            ((self.rasterLayer.hasScaleBasedVisibility() and
             self.rasterLayer.isInScaleRange(self.mapCanvas.scale())) or
                not self.rasterLayer.hasScaleBasedVisibility()):
            self.setEnabled(True)
        else:
            self.setEnabled(False)

    def activate(self, checked):
        """Activate or deactive the measurement action.
        Parameters
        ----------
        checked : boolean
            Current status of the toggle action. Start measurement if `True`,
            stop measurement if `False`.
        """
        if checked:
            self.startMeasure()
        else:
            self.stopMeasure()

    def startMeasure(self):
        """Start measuring.
        Add a PixelisedVectorLayer to the project and start drawing.
        """
        layer = PixelisedVectorLayer(self.main, rasterLayer=self.rasterLayer,
                                     path='Multipolygon?crs=epsg:31370',
                                     baseName='Pixelberekening',
                                     providerLib='memory')
        self.layer = QGisCore.QgsProject.instance().addMapLayer(layer, False)
        QGisCore.QgsProject.instance().layerTreeRoot().insertLayer(0, layer)
        self.main.iface.setActiveLayer(self.layer)
        self.main.iface.actionToggleEditing().trigger()
        self.main.iface.actionAddFeature().trigger()

    def stopMeasure(self):
        """Stop measuring.
        Remove memory layer from project.
        """
        self.setChecked(False)
        if self.layer:
            try:
                QGisCore.QgsProject.instance().removeMapLayer(
                    self.layer.id())
                self.main.iface.mapCanvas().refresh()
            except RuntimeError:
                pass
            self.layer = None

    def deactivate(self):
        """Deactivate by disconnecting signals and stopping measurement."""
        self.triggered.disconnect(self.startMeasure)
        self.mapCanvas.extentsChanged.connect(self.populateVisible)
        self.stopMeasure()
