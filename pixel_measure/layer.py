import PyQt5.QtGui as QtGui
import qgis.core as QGisCore

from .wrapper import RasterBlockWrapperTask


class PixelisedVectorLayer(QGisCore.QgsVectorLayer):
    """Class representing a pixelised polygon layer.
    This is a polygon layer that aligns features drawn onto it to the grid of
    a given raster layer. The border of all vector features overlap with the
    border of the grid cells of the rasterlayer.
    """

    def __init__(self, main, rasterLayer, path=None, baseName=None,
                 providerLib=None, loadDefaultStyleFlag=True):
        """Initialisation.
        Parameters
        ----------
        main : erosiebezwaren.Erosiebezwaren
            Instance of main class.
        rasterLayer : QGisCore.QgsRasterLayer
            Rasterlayer to use as the reference grid.
        path : str, optional
            The path or url of the parameter. Typically this encodes parameters
            used by the data provider as url query items.
        baseName : str, optional
            The name used to represent the layer in the legend.
        providerLib : str, optional
            The name of the data provider, eg "memory", "postgres".
        loadDefaultStyleFlag : boolean, optional, default `True`
            Whether to load the default style.
        """
        QGisCore.QgsVectorLayer.__init__(self, path, baseName, providerLib,
                                         QGisCore.QgsVectorLayer.LayerOptions(
                                             loadDefaultStyleFlag, readExtentFromXml=False))
        self.rasterLayer = rasterLayer
        self.main = main

        self._set_scaleBasedVisibility()
        self._set_labeling()

        self.editingStarted.connect(self._cb_editingStarted)
        self.beforeCommitChanges.connect(self._cb_beforeCommitChanges)

    def _set_scaleBasedVisibility(self):
        if self.rasterLayer.hasScaleBasedVisibility():
            self.setScaleBasedVisibility(True)
            self.setMinimumScale(self.rasterLayer.minimumScale())
            self.setMaximumScale(self.rasterLayer.maximumScale())
        else:
            self.setScaleBasedVisibility(False)

    def _set_labeling(self):
        props = self.renderer().symbol().symbolLayer(0).properties()
        props['color'] = '255,255,255,64'
        props['outline_color'] = '0,0,0,255'
        props['outline_width'] = '1'
        self.renderer().setSymbol(
            QGisCore.QgsFillSymbol.createSimple(props))

        label_settings = QGisCore.QgsPalLayerSettings()
        label_settings.enabled = True
        label_settings.placement = QGisCore.QgsPalLayerSettings.AroundPoint

        label_format = QGisCore.QgsTextFormat()
        label_format.setSize(12)
        label_format.setForcedBold(True)
        label_format.setColor(QtGui.QColor(0, 0, 0, 255))

        label_buffer = QGisCore.QgsTextBufferSettings()
        label_buffer.setEnabled(True)
        label_buffer.setSize(1.5)
        label_buffer.setColor(QtGui.QColor(255, 255, 255, 255))
        label_format.setBuffer(
            label_buffer
        )
        label_settings.setFormat(
            label_format
        )

        self.setLabeling(QGisCore.QgsVectorLayerSimpleLabeling(label_settings))
        self.setLabelsEnabled(True)

    def _cb_editingStarted(self):
        """Connect the featureAdded signal.
        Callback for the 'editingStarted' event.
        """
        self.editBuffer().featureAdded.connect(self._cb_featureAdded)

    def _cb_beforeCommitChanges(self):
        """Disconnect the featureAdded signal.
        Callback for the 'beforeCommitChanges' event.
        """
        self.editBuffer().featureAdded.disconnect(self._cb_featureAdded)

    def _cb_featureAdded(self, fid):
        """Pixelise the feature drawn.
        Align the polygon to the raster grid by creating a RasterBlockWrapper
        and updating the geometry of the feature. Also add the average
        (arithmetic mean) value of the cells of the newly created geometry as
        a label.

        Parameters
        ----------
        fid : int
            Feature id of the added feature.
        """
        def drawPixelisedFeature(result):
            geometry, stats = result
            if geometry is not None:
                self.changeGeometry(fid, geometry)

                label_settings = self.labeling().settings()
                label_settings.fieldName = "%0.2f" % stats['avg']
                label_settings.isExpression = True

                self.labeling().setSettings(label_settings)
                self.triggerRepaint()
            else:
                self.editBuffer().deleteFeature(fid)

            self.commitChanges()

        self.main.iface.actionPan().trigger()
        ft = next(self.getFeatures(QGisCore.QgsFeatureRequest(fid)))

        self.task = RasterBlockWrapperTask(self.rasterLayer, 1, ft.geometry())
        self.task.completed.connect(drawPixelisedFeature)
        QGisCore.QgsApplication.taskManager().addTask(self.task)
