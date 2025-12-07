# -*- coding: utf-8 -*-
"""
CELLULAR GROWTH SIMULATION FÜR RHINO
=====================================
Komplett überarbeitete Version mit:
- Sauberer Klassenstruktur
- Schöneren, glatteren Formen
- Licht-Abstand-Logik für dünne, verzweigte Strukturen
- Durchgehenden Löchern durch alle Ebenen
- Sanduhr-förmiger Layer-Konfiguration

Autor: Überarbeitet für bessere Architektur
"""

import rhinoscriptsyntax as rs
import Rhino
import Rhino.Geometry as rg
import random
import math
import time
from collections import deque

# ============================================================================
# KONFIGURATION
# ============================================================================

class Config:
    """Zentrale Konfiguration - alle Einstellungen an einem Ort"""
    
    # Grid-Einstellungen
    CELL_SIZE = 3.0
    MIN_WIDTH = 1  # Erlaubt einzelne Zellen-Linien für dünnere Strukturen
    MAX_LINE = 4
    
    # Layer-Konfiguration (Sanduhr-Form: breit → schmal → Mitte größer → schmal → oben größer)
    GROW_PER_GEN_LAYER = [50, 50, 35, 30, 25, 20, 28, 32, 30, 25, 20, 18, 15, 22, 25, 22, 18, 15, 12, 10]
    MIN_CELLS_LAYER = [300, 300, 200, 160, 120, 80, 120, 150, 140, 110, 80, 60, 50, 80, 100, 90, 70, 55, 45, 35]
    MAX_CELLS_LAYER = [400, 400, 280, 220, 170, 120, 170, 200, 190, 160, 120, 90, 75, 120, 150, 130, 100, 80, 65, 50]

    
    # Scoring-Gewichte
    WEIGHT_GROWTHPOINT = 2.0
    WEIGHT_CONNECTED = 1.8
    WEIGHT_SMOOTHNESS = 1.5      # NEU: Bevorzugt glatte Kanten
    WEIGHT_CONVEXITY = 1.2       # NEU: Bevorzugt konvexe Formen
    WEIGHT_LIGHT = 0.6
    WEIGHT_OBSTACLE = -1.2
    WEIGHT_LAYER_SUPPORT = 0.8
    
    # Harte Blockade für negative Wachstumspunkte
    HARD_BLOCKADE_THRESHOLD = -5  # Niedriger = frühere Blockade bei negativen Linien
    NEGATIVE_SCORE_WEIGHT = 0.3  # Höher = mehr Wachstum bei leicht negativen Scores
    STRONGLY_NEGATIVE_THRESHOLD = -20  # Schwellenwert für stark negative Scores (fast keine Chance)
    
    # Layer-Vererbung Einstellungen
    LAYER_INHERITANCE = 0.5      # Wie sehr folgt oberer Layer der Form des unteren (0.0-1.0)
    LAYER_GROWTH_FREEDOM = 0.3   # Erlaubt Überhänge/freies Wachstum (0.0-1.0)
    LAYER_SUPPORT_BONUS = 3.0    # Score-Bonus wenn Zelle unten existiert
    LAYER_OVERHANG_PENALTY = 2.0 # Score-Penalty für Überhänge (wenn Freedom < 1.0)
    STRICT_SUPPORT_THRESHOLD = 0.1  # Freedom-Wert unter dem strikt nur über existierenden Zellen gewachsen wird
    
    # Licht-Abstand-Einstellungen (Max Entfernung zur nächsten leeren Zelle/Außen)
    # Ersetzt die alte Loch-Logik - erzeugt dünne, verzweigte Strukturen
    LIGHT_DISTANCE = {
        "Work": 5,      # Max. 2 Zellen von Außen (sehr dünn)
        "Living": 7,    # Max. 3 Zellen von Außen
        "Industry": 10   # Max. 5 Zellen von Außen
    }
    DEFAULT_LIGHT_DISTANCE = 3  # Fallback wenn Funktion nicht definiert
    
    # Edge-Bonus-Einstellungen (fördert dünne, verzweigte Strukturen)
    EDGE_DISTANCE_THRESHOLD = 2  # Zellen mit Distanz <= Threshold bekommen Bonus
    EDGE_BONUS_SCORE = 3.0       # Score-Bonus für Zellen nah am Rand
    
    # Farben
    COLORS = {
        "Work": (200, 80, 80),
        "Living": (80, 200, 120),
        "Industry": (120, 120, 200),
        "Start": (255, 215, 0),
        "Obstacle": (60, 60, 60),
        "Default": (180, 180, 180)
    }
    
    # Abstände
    OBSTACLE_CLEARANCE = 1
    MEMBRANE_CLEARANCE = 0.5
    BOUNDARY_BUFFER = 0.1
    
    # Wachstum
    MAX_GROW_ATTEMPTS = 2000
    FRONTIER_RADIUS = 2
    
    # Visualisierung
    MAX_VISUAL_BOXES = 25000
    LAYER_NAME = "GrowthSimulation"
    PAUSE_BETWEEN_LAYERS = 0.1
    
    # Licht (Sonnenrichtung)
    SUN_DIRECTION = (0.5, 0.7, 0.8)  # Normalisiert


# ============================================================================
# GRID KLASSE
# ============================================================================

class Grid:
    """Verwaltet das 2D-Zellengitter für eine Ebene"""
    
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.cells = [[0] * cols for _ in range(rows)]
    
    def get(self, x, y):
        """Gibt Zellenwert zurück (0 = leer, 1 = belegt)"""
        if self.in_bounds(x, y):
            return self.cells[y][x]
        return 0
    
    def set(self, x, y, value):
        """Setzt Zellenwert"""
        if self.in_bounds(x, y):
            self.cells[y][x] = value
    
    def in_bounds(self, x, y):
        """Prüft ob Koordinaten im Grid liegen"""
        return 0 <= x < self.cols and 0 <= y < self.rows
    
    def is_empty(self, x, y):
        """Prüft ob Zelle leer ist"""
        return self.in_bounds(x, y) and self.cells[y][x] == 0
    
    def is_alive(self, x, y):
        """Prüft ob Zelle belegt ist"""
        return self.in_bounds(x, y) and self.cells[y][x] == 1
    
    def alive_count(self):
        """Zählt alle belegten Zellen"""
        return sum(sum(row) for row in self.cells)
    
    def neighbors_4(self, x, y):
        """Generator für 4-Nachbarn (N, S, E, W)"""
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny
    
    def neighbors_8(self, x, y):
        """Generator für 8-Nachbarn (inkl. Diagonale)"""
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny):
                    yield nx, ny
    
    def count_alive_neighbors_4(self, x, y):
        """Zählt lebende 4-Nachbarn"""
        return sum(1 for nx, ny in self.neighbors_4(x, y) if self.is_alive(nx, ny))
    
    def count_alive_neighbors_8(self, x, y):
        """Zählt lebende 8-Nachbarn"""
        return sum(1 for nx, ny in self.neighbors_8(x, y) if self.is_alive(nx, ny))
    
    def has_alive_neighbor_4(self, x, y):
        """Prüft ob mindestens ein 4-Nachbar lebt"""
        return any(self.is_alive(nx, ny) for nx, ny in self.neighbors_4(x, y))
    
    def get_component(self, start_x, start_y):
        """Findet zusammenhängende Komponente via BFS"""
        if not self.is_alive(start_x, start_y):
            return set()
        
        seen = set()
        queue = deque([(start_x, start_y)])
        seen.add((start_x, start_y))
        
        while queue:
            x, y = queue.popleft()
            for nx, ny in self.neighbors_4(x, y):
                if (nx, ny) not in seen and self.is_alive(nx, ny):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        
        return seen
    
    def get_all_alive_cells(self):
        """Gibt alle lebenden Zellen zurück"""
        cells = []
        for y in range(self.rows):
            for x in range(self.cols):
                if self.cells[y][x] == 1:
                    cells.append((x, y))
        return cells
    
    def copy(self):
        """Erstellt eine Kopie des Grids"""
        new_grid = Grid(self.cols, self.rows)
        for y in range(self.rows):
            for x in range(self.cols):
                new_grid.cells[y][x] = self.cells[y][x]
        return new_grid


# ============================================================================
# VERTICAL HOLES TRACKER - Durchgehende Löcher durch alle Ebenen
# ============================================================================

class VerticalHolesTracker:
    """
    Verwaltet Positionen die auf allen Ebenen leer bleiben müssen.
    Wenn Layer 0 an Position (x,y) leer ist, bleibt (x,y) auf allen Layern darüber leer.
    Dies wird durch die Licht-Abstand-Logik natürlich erzeugt.
    """
    
    def __init__(self):
        self.permanent_empty = set()  # Set von (x, y) Koordinaten die immer leer bleiben
    
    def add_permanent_empty(self, x, y):
        """Markiert Position als permanent leer (gilt für alle Ebenen)"""
        self.permanent_empty.add((x, y))
    
    def is_permanent_empty(self, x, y):
        """Prüft ob Position permanent leer sein muss"""
        return (x, y) in self.permanent_empty
    
    def get_all(self):
        """Gibt alle permanent leeren Positionen zurück"""
        return self.permanent_empty.copy()
    
    def count(self):
        """Anzahl der permanent leeren Positionen"""
        return len(self.permanent_empty)
    
    def clear(self):
        """Löscht alle Markierungen"""
        self.permanent_empty.clear()
    
    def sync_from_layer(self, grid, base_layer_grid=None):
        """
        Synchronisiert permanent leere Positionen aus einem Grid.
        Wenn base_layer_grid gegeben ist, werden Positionen die dort leer sind
        als permanent leer markiert.
        """
        if base_layer_grid:
            for y in range(base_layer_grid.rows):
                for x in range(base_layer_grid.cols):
                    if not base_layer_grid.is_alive(x, y):
                        # Position die auf Base-Layer leer ist, bleibt auf allen Ebenen leer
                        # (wird nur bei tatsächlichen "inneren" Löchern angewendet)
                        pass  # Nicht automatisch alle leeren Positionen markieren


# ============================================================================
# CONSTRAINTS - Grenzen, Membranen, Hindernisse
# ============================================================================

class Constraints:
    """Verwaltet alle räumlichen Einschränkungen"""
    
    def __init__(self, config, origin=(0, 0, 0)):
        self.config = config
        self.origin = origin
        self.cols = 0
        self.rows = 0
        
        # Kurven
        self.boundary_curve = None
        self.outer_lines = []
        self.membranes = []
        self.obstacles = []
        
        # Vorberechnete blockierte Zellen
        self.blocked_cells = set()
        self.obstacle_cells = set()
    
    def set_boundary(self, curve):
        """Setzt die Grundstücksgrenze und berechnet Grid-Größe"""
        self.boundary_curve = curve
        if curve:
            bbox = rs.BoundingBox([curve])
            if bbox:
                min_pt, max_pt = bbox[0], bbox[6]
                self.origin = (min_pt.X, min_pt.Y, min_pt.Z)
                
                width = max_pt.X - min_pt.X
                height = max_pt.Y - min_pt.Y
                
                self.cols = int(math.ceil(width / self.config.CELL_SIZE)) + 1
                self.rows = int(math.ceil(height / self.config.CELL_SIZE)) + 1
    
    def add_membrane(self, curve):
        """Fügt eine Membran hinzu"""
        if curve:
            self.membranes.append(curve)
    
    def add_outer_line(self, curve):
        """Fügt eine äußere Linie hinzu"""
        if curve:
            self.outer_lines.append(curve)
    
    def add_obstacle(self, curve):
        """Fügt ein Hindernis hinzu und berechnet blockierte Zellen"""
        if curve:
            self.obstacles.append(curve)
            self._compute_obstacle_cells(curve)
    
    def _compute_obstacle_cells(self, curve):
        """Berechnet welche Zellen durch ein Hindernis blockiert sind"""
        clearance = self.config.OBSTACLE_CLEARANCE
        
        for y in range(self.rows):
            for x in range(self.cols):
                center = self.cell_center_world(x, y)
                pt = rg.Point3d(center[0], center[1], center[2])
                
                # Prüfe Abstand zur Kurve
                try:
                    closest = curve.ClosestPoint(pt, 0.0)
                    if closest[0]:
                        dist = pt.DistanceTo(curve.PointAt(closest[1]))
                        if dist <= clearance * self.config.CELL_SIZE:
                            self.obstacle_cells.add((x, y))
                            self.blocked_cells.add((x, y))
                except:
                    pass
    
    def cell_center_world(self, x, y, layer=0):
        """Berechnet Weltkoordinaten der Zellenmitte"""
        ox, oy, oz = self.origin
        wx = ox + x * self.config.CELL_SIZE + self.config.CELL_SIZE * 0.5
        wy = oy + y * self.config.CELL_SIZE + self.config.CELL_SIZE * 0.5
        wz = oz + layer * self.config.CELL_SIZE
        return (wx, wy, wz)
    
    def world_to_cell(self, wx, wy):
        """Konvertiert Weltkoordinaten zu Grid-Koordinaten"""
        ox, oy, oz = self.origin
        x = int(math.floor((wx - ox) / self.config.CELL_SIZE))
        y = int(math.floor((wy - oy) / self.config.CELL_SIZE))
        return x, y
    
    def is_in_boundary(self, x, y):
        """Prüft ob Zelle innerhalb der Grundstücksgrenze liegt"""
        if not self.boundary_curve:
            return True
        
        center = self.cell_center_world(x, y)
        pt = rg.Point3d(center[0], center[1], 0)
        
        try:
            result = self.boundary_curve.Contains(pt, rg.Plane.WorldXY, 0.001)
            return result == rg.PointContainment.Inside
        except:
            return True
    
    def is_in_membrane(self, x, y):
        """Prüft ob Zelle innerhalb einer Membran liegt"""
        center = self.cell_center_world(x, y)
        pt = rg.Point3d(center[0], center[1], 0)
        
        for membrane in self.membranes:
            try:
                if hasattr(membrane, 'Contains'):
                    result = membrane.Contains(pt, rg.Plane.WorldXY, 0.001)
                    if result == rg.PointContainment.Inside:
                        return True
            except:
                pass
        return False
    
    def is_blocked_by_outer_line(self, x, y):
        """Prüft ob Zelle zu nah an einer äußeren Linie ist"""
        if not self.outer_lines:
            return False
        
        center = self.cell_center_world(x, y)
        pt = rg.Point3d(center[0], center[1], 0)
        clearance = self.config.MEMBRANE_CLEARANCE * self.config.CELL_SIZE
        
        for line in self.outer_lines:
            try:
                closest = line.ClosestPoint(pt, 0.0)
                if closest[0]:
                    dist = pt.DistanceTo(line.PointAt(closest[1]))
                    if dist <= clearance:
                        return True
            except:
                pass
        return False
    
    def is_allowed(self, x, y):
        """Zentrale Prüfung ob eine Zelle erlaubt ist"""
        # Bounds-Check
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return False
        
        # Blockierte Zellen
        if (x, y) in self.blocked_cells:
            return False
        
        # Boundary-Check
        if not self.is_in_boundary(x, y):
            return False
        
        # Membran-Check
        if self.is_in_membrane(x, y):
            return False
        
        # Äußere Linien
        if self.is_blocked_by_outer_line(x, y):
            return False
        
        return True


# ============================================================================
# GROWTH POINTS - Attraktoren/Repelloren
# ============================================================================

class GrowthPoint:
    """Ein Wachstumspunkt der Zellen anzieht oder abstößt"""
    
    def __init__(self, position, strength=1.0, radius=10.0, is_line=False, curve=None):
        self.position = position  # (x, y) oder None bei Linien
        self.strength = strength  # Positiv = anziehend, Negativ = abstoßend
        self.radius = radius      # Wirkungsradius in Zellen
        self.is_line = is_line
        self.curve = curve        # Rhino-Kurve bei Linien
    
    def get_influence(self, x, y, cell_size, origin):
        """Berechnet Einfluss auf eine Zelle"""
        if self.is_line and self.curve:
            return self._line_influence(x, y, cell_size, origin)
        else:
            return self._point_influence(x, y, cell_size, origin)
    
    def _point_influence(self, x, y, cell_size, origin):
        """Einfluss eines Punkt-Attraktors"""
        if not self.position:
            return 0.0
        
        ox, oy, _ = origin
        wx = ox + x * cell_size + cell_size * 0.5
        wy = oy + y * cell_size + cell_size * 0.5
        
        dx = wx - self.position[0]
        dy = wy - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        
        if dist > self.radius * cell_size:
            return 0.0
        
        # Linearer Abfall mit Distanz
        factor = 1.0 - (dist / (self.radius * cell_size))
        return self.strength * factor
    
    def _line_influence(self, x, y, cell_size, origin):
        """Einfluss einer Linien-Attraktor"""
        if not self.curve:
            return 0.0
        
        ox, oy, _ = origin
        wx = ox + x * cell_size + cell_size * 0.5
        wy = oy + y * cell_size + cell_size * 0.5
        pt = rg.Point3d(wx, wy, 0)
        
        try:
            closest = self.curve.ClosestPoint(pt, 0.0)
            if closest[0]:
                dist = pt.DistanceTo(self.curve.PointAt(closest[1]))
                if dist > self.radius * cell_size:
                    return 0.0
                factor = 1.0 - (dist / (self.radius * cell_size))
                return self.strength * factor
        except:
            pass
        
        return 0.0


# ============================================================================
# SMOOTHNESS CALCULATOR - Für glattere Formen
# ============================================================================

class SmoothnessCalculator:
    """Berechnet wie glatt/organisch eine Form ist"""
    
    @staticmethod
    def edge_count(grid, x, y):
        """
        Zählt wie viele Kanten die Zelle zur Außenwelt hätte.
        Weniger Kanten = glatter
        """
        edges = 0
        for nx, ny in grid.neighbors_4(x, y):
            if not grid.is_alive(nx, ny):
                edges += 1
        # Auch Rand zählt als Kante
        if x == 0 or x == grid.cols - 1:
            edges += 1
        if y == 0 or y == grid.rows - 1:
            edges += 1
        return edges
    
    @staticmethod
    def smoothness_score(grid, x, y):
        """
        Berechnet Glattheits-Score für eine potenzielle Zelle.
        Höher = besser (glatter)
        
        Bevorzugt:
        - Zellen die konkave Bereiche füllen
        - Zellen mit vielen Nachbarn
        - Zellen die keine "Halbinseln" erzeugen
        """
        score = 0.0
        
        # Mehr Nachbarn = besser (füllt Lücken)
        neighbors_4 = grid.count_alive_neighbors_4(x, y)
        neighbors_8 = grid.count_alive_neighbors_8(x, y)
        
        # Bonus für 4-Nachbarn (direkte Verbindung)
        score += neighbors_4 * 2.0
        
        # Bonus für 8-Nachbarn (diagonale = füllt Ecken)
        diagonal_neighbors = neighbors_8 - neighbors_4
        score += diagonal_neighbors * 1.5
        
        # Penalty für zu wenige Nachbarn (würde Halbinsel erzeugen)
        if neighbors_4 == 1:
            score -= 2.0  # Nur ein Nachbar = potenzielle Halbinsel
        
        # Bonus wenn Zelle eine "Ecke" füllt (2 orthogonale Nachbarn)
        if neighbors_4 == 2:
            # Prüfe ob die Nachbarn orthogonal sind (Ecke)
            alive_neighbors = [(nx, ny) for nx, ny in grid.neighbors_4(x, y) if grid.is_alive(nx, ny)]
            if len(alive_neighbors) == 2:
                n1, n2 = alive_neighbors
                if n1[0] != n2[0] and n1[1] != n2[1]:  # Orthogonal
                    score += 3.0  # Ecke füllen ist gut
        
        # Bonus wenn Zelle von 3 Seiten umgeben ist (füllt Bucht)
        if neighbors_4 >= 3:
            score += 4.0
        
        return score
    
    @staticmethod
    def convexity_score(grid, x, y):
        """
        Berechnet wie sehr die Zelle zur Konvexität beiträgt. 
        Höher = konvexer (besser)
        """
        # Zähle wie viele diagonale Ecken gefüllt wären
        corners_filled = 0
        corner_offsets = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        
        for dx, dy in corner_offsets:
            nx, ny = x + dx, y + dy
            if grid.is_alive(nx, ny):
                corners_filled += 1
        
        # Prüfe ob die Zelle eine "Einbuchtung" füllt
        # (beide orthogonalen Nachbarn einer Ecke sind belegt)
        filling_concave = 0
        for dx, dy in corner_offsets:
            nx1, ny1 = x + dx, y
            nx2, ny2 = x, y + dy
            if grid.is_alive(nx1, ny1) and grid.is_alive(nx2, ny2):
                # Diese Ecke wäre konkav ohne unsere Zelle
                if not grid.is_alive(x + dx, y + dy):
                    filling_concave += 1
        
        return corners_filled * 0.5 + filling_concave * 2.0


# ============================================================================
# GROWTH ENGINE - Hauptwachstumslogik
# ============================================================================

class GrowthEngine:
    """Steuert das Zellwachstum mit Licht-Abstand-Logik"""
    
    def __init__(self, config, constraints, vertical_holes_tracker):
        self.config = config
        self.constraints = constraints
        self.vertical_holes_tracker = vertical_holes_tracker
        self.growth_points = []
        self.start_cells = []
        self.smoothness = SmoothnessCalculator()
        self.current_function = "Living"  # Wird pro Layer gesetzt
    
    def add_growth_point(self, gp):
        """Fügt einen Growth Point hinzu"""
        self.growth_points.append(gp)
    
    def set_start_cells(self, cells):
        """Setzt die Startzellen"""
        self.start_cells = list(cells)
    
    def set_current_function(self, function):
        """Setzt die aktuelle Funktion für Licht-Abstand-Berechnung"""
        self.current_function = function
    
    def distance_to_outside(self, grid, x, y):
        """
        Berechnet den kürzesten Abstand von Zelle (x,y) zur nächsten leeren Zelle.
        Verwendet BFS (Breadth-First Search).
        
        Returns: int - Anzahl Schritte bis zur nächsten leeren Zelle
        """
        # Rand des Grids zählt als "außen" - prüfe zuerst
        if x == 0 or x == grid.cols - 1 or y == 0 or y == grid.rows - 1:
            return 1
        
        visited = set()
        queue = deque([(x, y, 0)])
        visited.add((x, y))
        
        while queue:
            cx, cy, dist = queue.popleft()
            
            for nx, ny in grid.neighbors_4(cx, cy):
                if (nx, ny) in visited:
                    continue
                
                # Leere Zelle gefunden = Außen/Licht!
                if grid.is_empty(nx, ny):
                    return dist + 1
                
                visited.add((nx, ny))
                queue.append((nx, ny, dist + 1))
        
        # Komplett eingeschlossen
        return 9999
    
    def score_candidate(self, grid, x, y, layer_index, lower_grid=None):
        """
        Berechnet Gesamtscore für eine Kandidatenzelle.
        Höher = besser
        """
        score = 0.0
        
        # 1. Growth Point Einfluss
        for gp in self.growth_points:
            influence = gp.get_influence(x, y, self.config.CELL_SIZE, self.constraints.origin)
            
            # Harte Blockade bei stark negativem Einfluss
            if influence < self.config.HARD_BLOCKADE_THRESHOLD:
                return float('-inf')  # Zelle wird NIEMALS gewählt
            
            score += influence * self.config.WEIGHT_GROWTHPOINT
        
        # 2. Verbindungs-Bonus (mehr Nachbarn = besser)
        neighbors = grid.count_alive_neighbors_4(x, y)
        score += neighbors * self.config.WEIGHT_CONNECTED
        
        # 3. Glattheits-Score
        smooth = self.smoothness.smoothness_score(grid, x, y)
        score += smooth * self.config.WEIGHT_SMOOTHNESS
        
        # 4. Konvexitäts-Score
        convex = self.smoothness.convexity_score(grid, x, y)
        score += convex * self.config.WEIGHT_CONVEXITY
        
        # 5. Layer-Unterstützung mit Vererbungs-Einstellungen
        if lower_grid:
            inheritance = self.config.LAYER_INHERITANCE
            freedom = self.config.LAYER_GROWTH_FREEDOM
            
            if lower_grid.is_alive(x, y):
                # Zelle existiert unten = Bonus (skaliert mit Inheritance)
                score += self.config.LAYER_SUPPORT_BONUS * inheritance
            else:
                # Keine Zelle unten = möglicher Penalty (skaliert mit 1-Freedom)
                penalty = self.config.LAYER_OVERHANG_PENALTY * (1.0 - freedom) * inheritance
                score -= penalty
        
        # 6. Licht-Score
        light = self._compute_light_score(x, y, layer_index)
        score += light * self.config.WEIGHT_LIGHT
        
        # 7. Distanz zu Hindernissen (Penalty)
        obstacle_penalty = self._compute_obstacle_penalty(x, y)
        score += obstacle_penalty * self.config.WEIGHT_OBSTACLE
        
        # 8. Bonus für Zellen nah am Rand (fördert dünne, verzweigte Strukturen)
        grid.set(x, y, 1)
        edge_dist = self.distance_to_outside(grid, x, y)
        grid.set(x, y, 0)
        if edge_dist <= self.config.EDGE_DISTANCE_THRESHOLD:
            score += self.config.EDGE_BONUS_SCORE
        
        return score
    
    def _compute_light_score(self, x, y, layer_index):
        """Berechnet Licht-Score basierend auf Sonnenrichtung"""
        sun = self.config.SUN_DIRECTION
        # Normalisiere Sonnenrichtung (nur x, y)
        sun_len = math.sqrt(sun[0]**2 + sun[1]**2)
        if sun_len == 0:
            return 0.5
        
        # Zellen in Sonnenrichtung bekommen mehr Licht
        center_x = self.constraints.cols / 2
        center_y = self.constraints.rows / 2
        
        dx = (x - center_x) / max(1, self.constraints.cols)
        dy = (y - center_y) / max(1, self.constraints.rows)
        
        # Dot product mit Sonnenrichtung
        dot = (dx * sun[0] + dy * sun[1]) / sun_len
        
        # Höhere Layer bekommen mehr Licht
        height_bonus = layer_index * 0.05
        
        return (dot + 1.0) / 2.0 + height_bonus
    
    def _compute_obstacle_penalty(self, x, y):
        """Berechnet Penalty für Nähe zu Hindernissen"""
        if (x, y) in self.constraints.obstacle_cells:
            return -10.0  # Stark negativ
        
        # Prüfe Nachbarschaft zu Hindernissen
        penalty = 0.0
        for nx, ny in [(x+1,y), (x-1,y), (x,y+1), (x,y-1)]:
            if (nx, ny) in self.constraints.obstacle_cells:
                penalty -= 0.5
        
        return penalty
    
    def can_place(self, grid, x, y, layer_index, lower_grid=None):
        """
        Prüft ob eine Zelle platziert werden darf.
        Enthält neue Licht-Abstand-Prüfung!
        """
        # Grundlegende Constraint-Prüfung
        if not self.constraints.is_allowed(x, y):
            return False
        
        # Durchgehendes Loch (von unteren Ebenen)?
        if self.vertical_holes_tracker.is_permanent_empty(x, y):
            return False
        
        # Bereits belegt?
        if grid.is_alive(x, y):
            return False
        
        # Muss mindestens einen 4-Nachbarn haben
        if not grid.has_alive_neighbor_4(x, y):
            return False
        
        # NEU: Bei sehr niedriger Freedom: Nur über existierenden Zellen wachsen
        if lower_grid and self.config.LAYER_GROWTH_FREEDOM < self.config.STRICT_SUPPORT_THRESHOLD:
            if not lower_grid.is_alive(x, y):
                return False
        
        # Mindestbreite prüfen
        if not self._check_min_width(grid, x, y):
            return False
        
        # Maximale Linienlänge prüfen
        if not self._check_max_line(grid, x, y):
            return False
        
        # Verbindung zur Startkomponente prüfen
        if not self._check_connectivity(grid, x, y):
            return False
        
        # NEU: Prüfe Licht-Abstand
        if not self._check_light_distance(grid, x, y):
            return False
        
        return True
    
    def _check_light_distance(self, grid, x, y):
        """
        Prüft ob Zelle noch nah genug am Licht/Außen wäre UND
        ob keine existierende Zelle dadurch zu weit weg gerät.
        Verhindert dass Zellen zu tief im Inneren platziert werden.
        """
        max_dist = self.config.LIGHT_DISTANCE.get(
            self.current_function, self.config.DEFAULT_LIGHT_DISTANCE)
        
        # Simuliere Platzierung
        grid.set(x, y, 1)
        try:
            # Prüfe die neue Zelle
            dist = self.distance_to_outside(grid, x, y)
            if dist > max_dist:
                return False
            
            # Prüfe alle Nachbarn der neuen Zelle
            for nx, ny in grid.neighbors_4(x, y):
                if grid.is_alive(nx, ny):
                    neighbor_dist = self.distance_to_outside(grid, nx, ny)
                    if neighbor_dist > max_dist:
                        return False
        finally:
            grid.set(x, y, 0)  # Zurücksetzen
        
        return True
    
    def _check_min_width(self, grid, x, y):
        """Prüft ob Mindestbreite erfüllt ist (horizontal oder vertikal)"""
        min_width = self.config.MIN_WIDTH
        
        # Horizontal zählen (inkl. Kandidat)
        count_h = 1
        # Links
        cx = x - 1
        while cx >= 0 and grid.is_alive(cx, y):
            count_h += 1
            cx -= 1
        # Rechts
        cx = x + 1
        while cx < grid.cols and grid.is_alive(cx, y):
            count_h += 1
            cx += 1
        
        # Vertikal zählen
        count_v = 1
        # Oben
        cy = y - 1
        while cy >= 0 and grid.is_alive(x, cy):
            count_v += 1
            cy -= 1
        # Unten
        cy = y + 1
        while cy < grid.rows and grid.is_alive(x, cy):
            count_v += 1
            cy += 1
        
        return count_h >= min_width or count_v >= min_width
    
    def _check_max_line(self, grid, x, y):
        """Prüft ob maximale Linienlänge nicht überschritten wird"""
        max_line = self.config.MAX_LINE
        
        # Gleiche Logik wie min_width, aber anderer Vergleich
        count_h = 1
        cx = x - 1
        while cx >= 0 and grid.is_alive(cx, y):
            count_h += 1
            cx -= 1
        cx = x + 1
        while cx < grid.cols and grid.is_alive(cx, y):
            count_h += 1
            cx += 1
        
        count_v = 1
        cy = y - 1
        while cy >= 0 and grid.is_alive(x, cy):
            count_v += 1
            cy -= 1
        cy = y + 1
        while cy < grid.rows and grid.is_alive(x, cy):
            count_v += 1
            cy += 1
        
        # Mindestens eine Achse muss <= MAX_LINE sein
        return count_h <= max_line or count_v <= max_line
    
    def _check_connectivity(self, grid, x, y):
        """Prüft ob Zelle zur Hauptkomponente verbunden wäre"""
        if not self.start_cells:
            return True
        
        # Finde eine lebende Startzelle
        start = None
        for sx, sy in self.start_cells:
            if grid.is_alive(sx, sy):
                start = (sx, sy)
                break
        
        if not start:
            # Keine lebende Startzelle, erlaube alles
            return True
        
        # Temporär setzen und prüfen
        grid.set(x, y, 1)
        component = grid.get_component(start[0], start[1])
        connected = (x, y) in component
        grid.set(x, y, 0)  # Zurücksetzen
        
        return connected
    
    def get_frontier_candidates(self, grid):
        """Findet alle Kandidatenzellen am Rand der aktuellen Form"""
        candidates = set()
        radius = self.config.FRONTIER_RADIUS
        
        for cx, cy in grid.get_all_alive_cells():
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if grid.is_empty(nx, ny) and self.constraints.is_allowed(nx, ny):
                        if not self.vertical_holes_tracker.is_permanent_empty(nx, ny):
                            candidates.add((nx, ny))
        
        return list(candidates)
    
    def grow_layer(self, grid, layer_index, lower_grid=None):
        """
        Hauptwachstumsalgorithmus für eine Ebene.
        Gibt Anzahl platzierter Zellen zurück.
        """
        # Layer-spezifische Konfiguration
        if layer_index < len(self.config.GROW_PER_GEN_LAYER):
            grow_count = self.config.GROW_PER_GEN_LAYER[layer_index]
            min_cells = self.config.MIN_CELLS_LAYER[layer_index]
            max_cells = self.config.MAX_CELLS_LAYER[layer_index]
        else:
            grow_count = self.config.GROW_PER_GEN_LAYER[-1]
            min_cells = self.config.MIN_CELLS_LAYER[-1]
            max_cells = self.config.MAX_CELLS_LAYER[-1]
        
        placed = 0
        attempts = 0
        
        while placed < grow_count and attempts < self.config.MAX_GROW_ATTEMPTS:
            candidates = self.get_frontier_candidates(grid)
            
            if not candidates:
                break
            
            # Score alle Kandidaten
            scored = []
            for (x, y) in candidates:
                if self.can_place(grid, x, y, layer_index, lower_grid):
                    s = self.score_candidate(grid, x, y, layer_index, lower_grid)
                    scored.append(((x, y), s))
            
            if not scored:
                attempts += 1
                continue
            
            # Filtere Kandidaten mit -inf Score aus (von harter Blockade in score_candidate)
            scored = [item for item in scored if item[1] != float('-inf')]
            
            if not scored:
                attempts += 1
                continue
            
            # Gewichtete Auswahl (höherer Score = höhere Wahrscheinlichkeit)
            scored.sort(key=lambda item: item[1], reverse=True)
            
            # Top-Kandidaten mit Gewichtung
            weights = []
            for i, (pos, s) in enumerate(scored[:20]):  # Top 20
                # Differenzierte Behandlung nach Score
                if s < self.config.STRONGLY_NEGATIVE_THRESHOLD:
                    weight = 0.001  # Stark negativ = fast keine Chance
                elif s < 0:
                    weight = self.config.NEGATIVE_SCORE_WEIGHT  # Leicht negativ = reduzierte Chance (0.3)
                else:
                    weight = math.exp(s * 0.5)  # Positiv = exponentiell
                weights.append(weight)
            
            if not weights:
                attempts += 1
                continue
            
            total_weight = sum(weights)
            if total_weight <= 0:
                pick = scored[0][0]
            else:
                # Gewichtete Zufallsauswahl
                r = random.random() * total_weight
                cumulative = 0
                pick = scored[0][0]
                for i, w in enumerate(weights):
                    cumulative += w
                    if r <= cumulative:
                        pick = scored[i][0]
                        break
            
            x, y = pick
            grid.set(x, y, 1)
            placed += 1
            attempts = 0  # Reset bei Erfolg
        
        # Mindestanzahl erreichen
        extra_attempts = 0
        while grid.alive_count() < min_cells and extra_attempts < 10:
            need = min_cells - grid.alive_count()
            grew = self._grow_extra(grid, need, layer_index, lower_grid)
            if grew == 0:
                break
            extra_attempts += 1
        
        # Maximale Anzahl einhalten
        if grid.alive_count() > max_cells:
            self._prune_to_max(grid, max_cells)
        
        return placed
    
    def _grow_extra(self, grid, count, layer_index, lower_grid):
        """Zusätzliches Wachstum um Minimum zu erreichen"""
        placed = 0
        attempts = 0
        
        while placed < count and attempts < 500:
            candidates = self.get_frontier_candidates(grid)
            if not candidates:
                break
            
            random.shuffle(candidates)
            
            for (x, y) in candidates[:10]:
                if self.can_place(grid, x, y, layer_index, lower_grid):
                    grid.set(x, y, 1)
                    placed += 1
                    break
            
            attempts += 1
        
        return placed
    
    def _prune_to_max(self, grid, max_cells):
        """Reduziert Zellen auf Maximum (entfernt Randzellen)"""
        while grid.alive_count() > max_cells:
            # Finde Randzellen (wenige Nachbarn)
            cells = grid.get_all_alive_cells()
            
            # Sortiere nach Anzahl Nachbarn (wenigste zuerst)
            cells_with_neighbors = [
                (x, y, grid.count_alive_neighbors_4(x, y))
                for x, y in cells
                if (x, y) not in self.start_cells  # Startzellen nicht entfernen
            ]
            cells_with_neighbors.sort(key=lambda c: c[2])
            
            if not cells_with_neighbors:
                break
            
            # Entferne Zelle mit wenigsten Nachbarn
            x, y, _ = cells_with_neighbors[0]
            
            # Prüfe ob Entfernen die Verbindung bricht
            grid.set(x, y, 0)
            
            # Prüfe Konnektivität
            if self.start_cells:
                start = None
                for sx, sy in self.start_cells:
                    if grid.is_alive(sx, sy):
                        start = (sx, sy)
                        break
                
                if start:
                    component = grid.get_component(start[0], start[1])
                    remaining = grid.get_all_alive_cells()
                    
                    if len(component) != len(remaining):
                        # Verbindung gebrochen - rückgängig machen
                        grid.set(x, y, 1)
                        # Markiere als nicht entfernbar und versuche nächste
                        continue
    
    def remove_isolated(self, grid):
        """Entfernt isolierte Zellen (keine 4-Nachbarn)"""
        to_remove = []
        for x, y in grid.get_all_alive_cells():
            if grid.count_alive_neighbors_4(x, y) == 0:
                if (x, y) not in self.start_cells:
                    to_remove.append((x, y))
        
        for x, y in to_remove:
            grid.set(x, y, 0)
    
    def enforce_start_cells(self, grid):
        """Stellt sicher dass alle Startzellen leben"""
        for x, y in self.start_cells:
            if grid.in_bounds(x, y) and self.constraints.is_allowed(x, y):
                grid.set(x, y, 1)
    
    def sync_vertical_holes_from_base(self, base_grid, boundary_grid):
        """
        Synchronisiert vertikale Löcher von der Basis-Ebene.
        Leere Positionen innerhalb der Boundary, die auf Basis-Ebene
        durch die Licht-Logik entstanden sind, werden für alle Ebenen markiert.
        """
        # Finde alle Positionen die innerhalb der besetzten Fläche leer sind
        # (d.h. "innere Löcher" die durch die Licht-Abstand-Logik entstanden sind)
        all_alive = set(base_grid.get_all_alive_cells())
        if not all_alive:
            return
        
        # Finde Bounding Box der besetzten Zellen
        min_x = min(x for x, y in all_alive)
        max_x = max(x for x, y in all_alive)
        min_y = min(y for x, y in all_alive)
        max_y = max(y for x, y in all_alive)
        
        # Prüfe alle Positionen in der Bounding Box
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if not base_grid.is_alive(x, y):
                    # Prüfe ob Position "innen" liegt (hat Nachbarn auf allen Seiten)
                    has_left = any(base_grid.is_alive(nx, y) for nx in range(0, x))
                    has_right = any(base_grid.is_alive(nx, y) for nx in range(x + 1, base_grid.cols))
                    has_top = any(base_grid.is_alive(x, ny) for ny in range(0, y))
                    has_bottom = any(base_grid.is_alive(x, ny) for ny in range(y + 1, base_grid.rows))
                    
                    if has_left and has_right and has_top and has_bottom:
                        # Dies ist ein "inneres Loch" - markiere als durchgehend
                        self.vertical_holes_tracker.add_permanent_empty(x, y)


# ============================================================================
# VISUALIZER - Rhino Visualisierung
# ============================================================================

class Visualizer:
    """Erstellt 3D-Boxen in Rhino"""
    
    def __init__(self, config, constraints):
        self.config = config
        self.constraints = constraints
        self.cell_objects = {}  # (x, y, layer) -> GUID
        self.visual_count = 0
    
    def ensure_layer(self):
        """Erstellt Layer falls nicht vorhanden"""
        if not rs.IsLayer(self.config.LAYER_NAME):
            rs.AddLayer(self.config.LAYER_NAME)
        return self.config.LAYER_NAME
    
    def make_box(self, x, y, layer, color):
        """Erstellt eine Box für eine Zelle"""
        if self.visual_count >= self.config.MAX_VISUAL_BOXES:
            return None
        
        cell = self.config.CELL_SIZE
        ox, oy, oz = self.constraints.origin
        
        x0 = ox + x * cell
        y0 = oy + y * cell
        z0 = oz + layer * cell
        z1 = z0 + cell
        
        corners = [
            (x0, y0, z0),
            (x0 + cell, y0, z0),
            (x0 + cell, y0 + cell, z0),
            (x0, y0 + cell, z0),
            (x0, y0, z1),
            (x0 + cell, y0, z1),
            (x0 + cell, y0 + cell, z1),
            (x0, y0 + cell, z1)
        ]
        
        try:
            box = rs.AddBox(corners)
            if box:
                rs.ObjectColor(box, color)
                rs.ObjectLayer(box, self.config.LAYER_NAME)
                self.visual_count += 1
                return box
        except:
            pass
        
        return None
    
    def add_layer(self, grid, layer_index, layer_function, start_cells):
        """Fügt NUR die Boxen eines neuen Layers hinzu (ohne alte zu löschen)"""
        self.ensure_layer()
        
        # Farbe für diesen Layer
        color = self.config.COLORS.get(layer_function, self.config.COLORS["Default"])
        
        rs.EnableRedraw(False)
        
        for y in range(grid.rows):
            for x in range(grid.cols):
                if self.visual_count >= self.config.MAX_VISUAL_BOXES:
                    rs.EnableRedraw(True)
                    return
                
                if grid.is_alive(x, y):
                    # Nur erstellen wenn noch nicht existiert
                    if (x, y, layer_index) not in self.cell_objects:
                        if (x, y) in start_cells:
                            draw_color = self.config.COLORS["Start"]
                        else:
                            draw_color = color
                        
                        guid = self.make_box(x, y, layer_index, draw_color)
                        if guid:
                            self.cell_objects[(x, y, layer_index)] = guid
        
        rs.EnableRedraw(True)
    
    def update(self, layers, layer_functions, start_cells, vertical_holes_tracker):
        """Aktualisiert die komplette Visualisierung"""
        self.ensure_layer()
        
        # Alte Objekte löschen
        to_delete = []
        for coord, guid in list(self.cell_objects.items()):
            if guid and rs.IsObject(guid):
                to_delete.append(guid)
        
        if to_delete:
            rs.DeleteObjects(to_delete)
        
        self.cell_objects.clear()
        self.visual_count = 0
        
        # Neue Boxen erstellen
        for layer_index, grid in enumerate(layers):
            # Farbe basierend auf Funktion
            if layer_index < len(layer_functions):
                func = layer_functions[layer_index]
                color = self.config.COLORS.get(func, self.config.COLORS["Default"])
            else:
                color = self.config.COLORS["Default"]
            
            for y in range(grid.rows):
                for x in range(grid.cols):
                    if self.visual_count >= self.config.MAX_VISUAL_BOXES:
                        return
                    
                    if grid.is_alive(x, y):
                        # Startzellen bekommen Spezialfarbe
                        if (x, y) in start_cells:
                            draw_color = self.config.COLORS["Start"]
                        else:
                            draw_color = color
                        
                        guid = self.make_box(x, y, layer_index, draw_color)
                        if guid:
                            self.cell_objects[(x, y, layer_index)] = guid
    
    def clear(self):
        """Löscht alle visualisierten Objekte"""
        to_delete = []
        for guid in self.cell_objects.values():
            if guid and rs.IsObject(guid):
                to_delete.append(guid)
        
        if to_delete:
            rs.DeleteObjects(to_delete)
        
        self.cell_objects.clear()
        self.visual_count = 0


# ============================================================================
# USER INTERFACE - Benutzerinteraktion
# ============================================================================

class UI:
    """Benutzerinteraktion in Rhino"""
    
    def __init__(self, config):
        self.config = config
    
    def ask_integer(self, prompt, default, minimum=1, maximum=100):
        """Fragt nach einer Ganzzahl"""
        result = rs.GetInteger(prompt, default, minimum, maximum)
        return result if result is not None else default
    
    def ask_string(self, prompt, default, options=None):
        """Fragt nach einem String"""
        if options:
            result = rs.GetString(prompt, default, options)
        else:
            result = rs.GetString(prompt, default)
        return result if result else default
    
    def ask_yes_no(self, prompt, title="Frage"):
        """Ja/Nein Dialog"""
        result = rs.MessageBox(prompt, 4 | 32, title)
        return result == 6  # 6 = Ja
    
    def show_message(self, message, title="Info"):
        """Zeigt eine Nachricht"""
        rs.MessageBox(message, 0, title)
    
    def choose_boundary(self):
        """Lässt Benutzer Grundstücksgrenze wählen"""
        self.show_message("Bitte wähle die Grundstücksgrenze (geschlossene Kurve)")
        curve_id = rs.GetObject("Grundstücksgrenze wählen", rs.filter.curve)
        
        if not curve_id:
            return None
        
        curve = rs.coercecurve(curve_id)
        if not curve:
            self.show_message("Keine gültige Kurve gewählt", "Fehler")
            return None
        
        if not curve.IsClosed:
            self.show_message("Kurve muss geschlossen sein", "Fehler")
            return None
        
        return curve
    
    def choose_membranes(self):
        """Lässt Benutzer Membranen wählen"""
        membranes = []
        
        while True:
            if not self.ask_yes_no("Membran hinzufügen? ", "Membranen"):
                break
            
            curve_id = rs.GetObject("Membran wählen (geschlossene Kurve)", rs.filter.curve)
            if curve_id:
                curve = rs.coercecurve(curve_id)
                if curve and curve.IsClosed:
                    membranes.append(curve)
                else:
                    self.show_message("Membran muss geschlossene Kurve sein")
        
        return membranes
    
    def choose_outer_lines(self):
        """Lässt Benutzer äußere Linien wählen"""
        lines = []
        
        if not self.ask_yes_no("Äußere Membran-Linien setzen?", "Äußere Linien"):
            return lines
        
        curve_ids = rs.GetObjects("Äußere Linien wählen", rs.filter.curve)
        if curve_ids:
            for cid in curve_ids:
                curve = rs.coercecurve(cid)
                if curve:
                    lines.append(curve)
        
        return lines
    
    def choose_obstacles(self):
        """Lässt Benutzer Hindernisse wählen"""
        obstacles = []
        
        curve_ids = rs.GetObjects("Hindernisse wählen (optional)", rs.filter.curve)
        if curve_ids:
            for cid in curve_ids:
                curve = rs.coercecurve(cid)
                if curve:
                    obstacles.append(curve)
        
        return obstacles
    
    def choose_start_cell(self, constraints):
        """Lässt Benutzer Startzelle wählen"""
        prompt = "Klicke Startzelle oder Enter für Koordinaten"
        pt = rs.GetPoint(prompt)
        
        if pt:
            x, y = constraints.world_to_cell(pt.X, pt.Y)
        else:
            default_x = constraints.cols // 2
            default_y = constraints.rows // 2
            x = self.ask_integer("Start X", default_x, 0, constraints.cols - 1)
            y = self.ask_integer("Start Y", default_y, 0, constraints.rows - 1)
        
        # Anzahl Startzellen
        count_str = self.ask_string("Startzellen: 1, 4 oder 9? ", "1", ["1", "4", "9"])
        try:
            count = int(count_str)
        except:
            count = 1
        
        if count not in [1, 4, 9]:
            count = 1
        
        # Generiere Positionen
        positions = []
        if count == 1:
            positions = [(x, y)]
        elif count == 4:
            for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
                positions.append((x + dx, y + dy))
        elif count == 9:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    positions.append((x + dx, y + dy))
        
        # Filtere ungültige Positionen
        valid = []
        for px, py in positions:
            if constraints.is_allowed(px, py):
                valid.append((px, py))
        
        if not valid:
            self.show_message("Keine gültigen Startzellen gefunden", "Fehler")
            return []
        
        return valid
    
    def choose_growth_points(self, config, constraints):
        """Lässt Benutzer Growth Points wählen"""
        growth_points = []
        
        while True:
            if not self.ask_yes_no("Growth Point hinzufügen?", "Growth Points"):
                break
            
            gp_type = self.ask_string("Typ: Punkt oder Linie?", "Punkt", ["Punkt", "Linie"])
            
            strength = rs.GetReal("Stärke (positiv=anziehend, negativ=abstoßend)", 1.0)
            if strength is None:
                strength = 1.0
            
            radius = rs.GetReal("Wirkungsradius (Zellen)", 10.0)
            if radius is None:
                radius = 10.0
            
            if gp_type == "Linie":
                curve_id = rs.GetObject("Linie wählen", rs.filter.curve)
                if curve_id:
                    curve = rs.coercecurve(curve_id)
                    if curve:
                        gp = GrowthPoint(None, strength, radius, is_line=True, curve=curve)
                        growth_points.append(gp)
            else:
                pt = rs.GetPoint("Growth Point Position")
                if pt:
                    gp = GrowthPoint((pt.X, pt.Y), strength, radius)
                    growth_points.append(gp)
        
        return growth_points
    
    def choose_layer_inheritance(self):
        """Fragt nach Layer-Vererbungs-Einstellungen"""
        inheritance = rs.GetReal("Layer Vererbung (0.0=frei, 1.0=strikt)", 0.5, 0.0, 1.0)
        if inheritance is None:
            inheritance = 0.5
        
        freedom = rs.GetReal("Wachstumsfreiheit (0.0=keine Überhänge, 1.0=frei)", 0.3, 0.0, 1.0)
        if freedom is None:
            freedom = 0.3
        
        return inheritance, freedom
    
    def choose_layer_config(self):
        """Fragt nach Layer-Anzahl und Funktionen"""
        count = self.ask_integer("Wie viele Layer? ", 20, 1, 50)
        
        functions = []
        for i in range(count):
            default = ["Work", "Living", "Industry"][i % 3]
            func = self.ask_string(
                "Funktion für Layer {} (Work/Living/Industry)".format(i),
                default,
                ["Work", "Living", "Industry"]
            )
            functions.append(func)
        
        return count, functions


# ============================================================================
# SIMULATION - Hauptklasse
# ============================================================================

class Simulation:
    """Steuert die gesamte Simulation mit Licht-Abstand-Logik"""
    
    def __init__(self):
        self.config = Config()
        self.ui = UI(self.config)
        self.constraints = None
        self.vertical_holes_tracker = VerticalHolesTracker()
        self.growth_engine = None
        self.visualizer = None
        self.layers = []
        self.layer_functions = []
        self.start_cells = []
    
    def _shrink_to_target(self, grid, target_cells):
        """Reduziert Zellen auf Zielanzahl (entfernt Randzellen von außen nach innen)"""
        while grid.alive_count() > target_cells:
            cells = grid.get_all_alive_cells()
            
            # Sortiere nach Anzahl Nachbarn (wenigste zuerst = Rand)
            cells_with_neighbors = [
                (x, y, grid.count_alive_neighbors_4(x, y))
                for x, y in cells
                if (x, y) not in self.start_cells
            ]
            cells_with_neighbors.sort(key=lambda c: c[2])
            
            if not cells_with_neighbors:
                break
            
            # Entferne Zelle mit wenigsten Nachbarn
            x, y, _ = cells_with_neighbors[0]
            
            # Prüfe ob Entfernen die Verbindung bricht
            grid.set(x, y, 0)
            
            # Prüfe Konnektivität
            if self.start_cells:
                start = None
                for sx, sy in self.start_cells:
                    if grid.is_alive(sx, sy):
                        start = (sx, sy)
                        break
                
                if start:
                    component = grid.get_component(start[0], start[1])
                    remaining = grid.get_all_alive_cells()
                    
                    if len(component) != len(remaining):
                        # Verbindung gebrochen - rückgängig machen
                        grid.set(x, y, 1)
    
    def run(self):
        """Führt die komplette Simulation aus"""
        print("=" * 50)
        print("CELLULAR GROWTH SIMULATION")
        print("Mit Licht-Abstand-Logik für dünne, verzweigte Strukturen")
        print("=" * 50)
        
        # 1. Layer-Konfiguration
        layer_count, self.layer_functions = self.ui.choose_layer_config()
        print("Layer: {}, Funktionen: {}".format(layer_count, self.layer_functions))
        
        # 2. Grundstücksgrenze
        boundary = self.ui.choose_boundary()
        if not boundary:
            self.ui.show_message("Keine Grenze gewählt - Abbruch")
            return
        
        # 3. Constraints aufbauen
        self.constraints = Constraints(self.config)
        self.constraints.set_boundary(boundary)
        print("Grid: {} x {} Zellen".format(self.constraints.cols, self.constraints.rows))
        
        # Sicherheitsprüfung
        if self.constraints.cols * self.constraints.rows > 300000:
            self.ui.show_message("Grid zu groß! Bitte kleinere Grenze oder größere Zellengröße.")
            return
        
        # 4. Äußere Linien
        for line in self.ui.choose_outer_lines():
            self.constraints.add_outer_line(line)
        
        # 5. Membranen
        for membrane in self.ui.choose_membranes():
            self.constraints.add_membrane(membrane)
        
        # 6. Startzellen
        self.start_cells = self.ui.choose_start_cell(self.constraints)
        if not self.start_cells:
            self.ui.show_message("Keine Startzellen - Abbruch")
            return
        print("Startzellen: {}".format(self.start_cells))
        
        # 7. Hindernisse
        for obstacle in self.ui.choose_obstacles():
            self.constraints.add_obstacle(obstacle)
        
        # 8. Growth Engine erstellen
        self.growth_engine = GrowthEngine(self.config, self.constraints, self.vertical_holes_tracker)
        self.growth_engine.set_start_cells(self.start_cells)
        
        # 9. Growth Points
        for gp in self.ui.choose_growth_points(self.config, self.constraints):
            self.growth_engine.add_growth_point(gp)
        
        # 10. Layer-Vererbung Einstellungen
        inheritance, freedom = self.ui.choose_layer_inheritance()
        self.config.LAYER_INHERITANCE = inheritance
        self.config.LAYER_GROWTH_FREEDOM = freedom
        print("Layer-Vererbung: {}, Wachstumsfreiheit: {}".format(inheritance, freedom))
        
        # 11. Visualizer
        self.visualizer = Visualizer(self.config, self.constraints)
        self.visualizer.ensure_layer()
        
        # 12. Simulation starten
        self._run_simulation(layer_count)
        
        # 13. Ergebnis
        total = sum(grid.alive_count() for grid in self.layers)
        holes = self.vertical_holes_tracker.count()
        print("=" * 50)
        print("FERTIG!")
        print("Gesamt Zellen: {}".format(total))
        print("Durchgehende vertikale Schächte: {}".format(holes))
        print("=" * 50)
    
    def _run_simulation(self, layer_count):
        """Führt die Layer-Simulation aus mit Licht-Abstand-Logik"""
        
        # Erste Ebene erstellen
        base_grid = Grid(self.constraints.cols, self.constraints.rows)
        
        # Startzellen setzen
        for x, y in self.start_cells:
            base_grid.set(x, y, 1)
        
        # Funktion für erste Ebene setzen
        func = self.layer_functions[0] if self.layer_functions else "Living"
        self.growth_engine.set_current_function(func)
        
        # Initiales Wachstum
        initial_grow = self.config.GROW_PER_GEN_LAYER[0] * 2
        print("Layer 0: Wachstum mit Licht-Abstand {} (Funktion: {})...".format(
            self.config.LIGHT_DISTANCE.get(func, 5), func))
        
        self.growth_engine.grow_layer(base_grid, 0, None)
        self.growth_engine.remove_isolated(base_grid)
        self.growth_engine.enforce_start_cells(base_grid)
        
        # Synchronisiere vertikale Löcher von der Basis-Ebene
        # (Positionen die durch die Licht-Logik leer bleiben)
        self.growth_engine.sync_vertical_holes_from_base(base_grid, None)
        
        self.layers.append(base_grid)
        print("Layer 0: {} Zellen".format(base_grid.alive_count()))
        
        # Visualisierung - nur Layer 0 hinzufügen (inkrementell)
        self.visualizer.add_layer(base_grid, 0, func, self.start_cells)
        Rhino.RhinoDoc.ActiveDoc.Views.Redraw()
        
        # Weitere Ebenen
        for layer_idx in range(1, layer_count):
            # Funktion für diese Ebene setzen
            func = self.layer_functions[layer_idx] if layer_idx < len(self.layer_functions) else "Living"
            self.growth_engine.set_current_function(func)
            
            # Hole max_cells für diesen Layer
            if layer_idx < len(self.config.MAX_CELLS_LAYER):
                max_cells = self.config.MAX_CELLS_LAYER[layer_idx]
            else:
                max_cells = self.config.MAX_CELLS_LAYER[-1]
            
            print("Layer {}: Organisches Wachstum mit max {} Zellen (Funktion: {})...".format(
                layer_idx, max_cells, func))
            
            # NEU: Echtes Wachstum statt nur Kopieren
            prev_grid = self.layers[-1]
            new_grid = Grid(self.constraints.cols, self.constraints.rows)
            
            # Startzellen setzen
            for x, y in self.start_cells:
                if self.constraints.is_allowed(x, y):
                    new_grid.set(x, y, 1)
            
            # Durchgehende Löcher anwenden (von unteren Ebenen)
            for (hx, hy) in self.vertical_holes_tracker.get_all():
                new_grid.set(hx, hy, 0)
            
            # ECHTES WACHSTUM mit prev_grid als lower_grid Referenz!
            self.growth_engine.grow_layer(new_grid, layer_idx, prev_grid)
            
            self.growth_engine.remove_isolated(new_grid)
            self.growth_engine.enforce_start_cells(new_grid)
            
            # Durchgehende Löcher nochmal anwenden
            for (hx, hy) in self.vertical_holes_tracker.get_all():
                new_grid.set(hx, hy, 0)
            
            self.layers.append(new_grid)
            print("Layer {}: {} Zellen".format(layer_idx, new_grid.alive_count()))
            
            # Visualisierung aktualisieren - nur neuen Layer hinzufügen (inkrementell)
            self.visualizer.add_layer(new_grid, layer_idx, func, self.start_cells)
            Rhino.RhinoDoc.ActiveDoc.Views.Redraw()
            
            time.sleep(0.1)
        
        print("Simulation fertig!")


def main():
    """Startet die Simulation"""
    try:
        sim = Simulation()
        sim.run()
    except Exception as e:
        print("FEHLER: {}".format(str(e)))
        rs.MessageBox("Fehler: {}".format(str(e)), 0, "Fehler")


if __name__ == "__main__":
    main()
else:
    main()