from multiprocessing import Lock
import PyQt5.QtCore as QtCore
import qgis.core as QGisCore

from .pool import WorkerThreadPool


class RasterBlockWrapperTask(QGisCore.QgsTask):
    """Class to align a vector geometry to the grid of a raster layer."""

    completed = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal()

    def __init__(self, rasterLayer, band, geometry):
        """Initialisation.
        Aligns the given geometry to the grid of the raster layer.
        Parameters
        ----------
        rasterLayer : QGisCore.QgsRasterLayer
            The raster layer to use as the grid to align the geometry to.
        band : int
            The band of the rasterlayer to use to calculate summary statistics
            for the new geometry.
        geometry : QGisCore.QgsGeometry
            Geometry to align to the raster grid.
        """
        super().__init__('Pixelwaarde berekenen', QGisCore.QgsTask.CanCancel)
        self.setDependentLayers([rasterLayer])
        self.shouldCancel = False

        self.rasterLayer = rasterLayer
        self.band = band
        self.geometry = geometry

        self.geomBbox = self.geometry.boundingBox()

        self.pixelSizeX = self.rasterLayer.rasterUnitsPerPixelX()
        self.pixelSizeY = self.rasterLayer.rasterUnitsPerPixelY()
        self.pixelArea = self.pixelSizeX*self.pixelSizeY

        self._buffer = max(self.pixelSizeX, self.pixelSizeY)
        self.geomBbox = self.geomBbox.buffered(self._buffer)

        self.blockBbox = self._alignRectangleToGrid(self.geomBbox)
        self.blockWidth = int(self.blockBbox.width()/self.pixelSizeX)
        self.blockHeight = int(self.blockBbox.height()/self.pixelSizeY)
        self.block = self.rasterLayer.dataProvider().block(self.band,
                                                           self.blockBbox,
                                                           self.blockWidth,
                                                           self.blockHeight)

        self.stats = {}
        self.newGeometry = None

    def _alignRectangleToGrid(self, rect):
        """Aligns the given rectangle to the grid of the raster layer.
        Parameters
        ----------
        rect : QGisCore.QgsRectangle
            Rectangle to align.
        Returns
        -------
        QGisCore.QgsRectangle
            New rectangle, aligned to the grid of the raster layer.
        """
        rasterExtent = self.rasterLayer.extent()
        newRect = QGisCore.QgsRectangle()
        newRect.setXMinimum(rasterExtent.xMinimum() + (round(
            (rect.xMinimum()-rasterExtent.xMinimum()) / self.pixelSizeX) *
            self.pixelSizeX))
        newRect.setYMinimum(rasterExtent.yMinimum() + (round(
            (rect.yMinimum()-rasterExtent.yMinimum()) / self.pixelSizeY) *
            self.pixelSizeY))
        newRect.setXMaximum(newRect.xMinimum() + (int(
            rect.width()/self.pixelSizeX)*self.pixelSizeX))
        newRect.setYMaximum(newRect.yMinimum() + (int(
            rect.height()/self.pixelSizeY)*self.pixelSizeY))
        return newRect

    def _rasterCellMatchesGeometry(self, rect):
        """Check whether a given raster cell belongs to the geometry.
        In casu: a raster cell belongs to the geometry if at least 50 percent
        of the area of the raster cell falls inside the geometry.
        Parameters
        ----------
        rect : QGisCore.QgsRectangle
            The rectangle representing the raster cell.
        Returns
        -------
        boolean
            `True` if the raster cell belongs to the geometry, `False`
            otherwise.
        """
        # 50% overlap
        return self.geometry.intersection(
            QGisCore.QgsGeometry.fromRect(rect)).area() >= (self.pixelArea*0.5)

    def run(self):
        """Calculate the new, aligned, geometry.
        Loop over all raster cells within the bounding box of the geometry and
        check for each of them if they should be part of the new geometry.
        Build a new QgsGeometry from the matching cells.
        Also builds a dictionary of statistics for the new QgsGeometry: listing
        the count, sum and average (mean) values of the raster cells it
        contains.
        """
        valSum = 0
        valCnt = 0

        self.progressDone = 0
        self.progressTodo = self.blockHeight * self.blockWidth * 2
        self.lock = Lock()

        noData = None
        if self.rasterLayer.dataProvider().sourceHasNoDataValue(self.band):
            noData = self.rasterLayer.dataProvider().sourceNoDataValue(self.band)

        def processPixel(r, c):
            cellRect = QGisCore.QgsRectangle()
            cellRect.setXMinimum(self.blockBbox.xMinimum() +
                                 (c*self.pixelSizeX))
            cellRect.setYMinimum(self.blockBbox.yMaximum() -
                                 (r*self.pixelSizeY)-self.pixelSizeY)
            cellRect.setXMaximum(self.blockBbox.xMinimum() +
                                 (c*self.pixelSizeX)+self.pixelSizeX)
            cellRect.setYMaximum(self.blockBbox.yMaximum() -
                                 (r*self.pixelSizeY))
            if self._rasterCellMatchesGeometry(cellRect):
                value = self.block.value(r, c)

                if noData and value == noData:
                    return None, None

                return QGisCore.QgsGeometry.fromRect(cellRect), value

            return None, None

        def aggregateGeometry(aggregate, item):
            if aggregate is None:
                return item

            if item is not None:
                return aggregate.combine(item)

            return aggregate

        def progressTracker():
            self.progressDone += 1
            self.setProgress((self.progressDone / self.progressTodo) * 100)

        def cancelFunction():
            return self.shouldCancel

        processPixelPool = WorkerThreadPool(progress_function=progressTracker)
        aggregateGeomPool = WorkerThreadPool(
            progress_function=progressTracker, cancel_function=cancelFunction, aggregation_function=aggregateGeometry)

        for r in range(self.blockHeight):
            for c in range(self.blockWidth):
                if self.shouldCancel:
                    break

                processPixelPool.execute(processPixel, (r, c))

            if self.shouldCancel:
                break

        for res in processPixelPool.join():
            if self.shouldCancel:
                self.failed.emit()
                return False

            rect, value = res.get_result()

            if rect is not None and value is not None:
                valSum += value
                valCnt += 1

                aggregateGeomPool.execute(lambda x: x, (rect,))
            else:
                progressTracker()

        for res in aggregateGeomPool.join():
            if self.shouldCancel:
                self.failed.emit()
                return False

            geom = res.get_result()
            self.newGeometry = aggregateGeometry(self.newGeometry, geom)

        if valCnt > 0:
            self.stats['sum'] = valSum
            self.stats['count'] = valCnt
            self.stats['avg'] = valSum/float(valCnt)

        self.completed.emit((self.newGeometry, self.stats))
        return True

    def cancel(self):
        self.shouldCancel = True
