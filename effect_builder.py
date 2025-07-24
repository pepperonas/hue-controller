#!/usr/bin/env python3
"""
Effekt-Builder System für Hue by mrx3k1
Drag & Drop Interface für Custom-Effekte
"""

import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import mysql.connector

@dataclass
class EffectStep:
    """Einzelner Schritt in einem Custom-Effekt"""
    id: str
    type: str  # 'color', 'brightness', 'transition', 'delay', 'loop'
    duration: float  # Dauer in Sekunden
    parameters: Dict[str, Any]
    target_type: str  # 'light', 'group', 'all'
    target_id: Optional[str] = None

@dataclass
class CustomEffect:
    """Definition eines Custom-Effekts"""
    id: str
    name: str
    description: str
    category: str
    author: str
    created_at: str
    steps: List[EffectStep]
    tags: List[str]
    preview_colors: List[str]  # Hex-Farben für Preview
    is_public: bool = False

class EffectBuilder:
    """Builder-Klasse für Custom-Effekte"""
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.predefined_templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, Any]:
        """Vordefinierte Effekt-Templates laden"""
        return {
            'color_wave': {
                'name': 'Farbwelle',
                'description': 'Farben laufen nacheinander durch alle Lichter',
                'steps': [
                    {
                        'type': 'color',
                        'duration': 2.0,
                        'parameters': {'hue': 0, 'sat': 255, 'bri': 200},
                        'target_type': 'all'
                    },
                    {
                        'type': 'transition',
                        'duration': 1.0,
                        'parameters': {'hue': 15000, 'sat': 255, 'bri': 200},
                        'target_type': 'all'
                    },
                    {
                        'type': 'transition',
                        'duration': 1.0,
                        'parameters': {'hue': 30000, 'sat': 255, 'bri': 200},
                        'target_type': 'all'
                    }
                ],
                'preview_colors': ['#FF0000', '#00FF00', '#0000FF']
            },
            'breathing': {
                'name': 'Atemeffekt',
                'description': 'Sanftes Ein- und Ausblenden',
                'steps': [
                    {
                        'type': 'brightness',
                        'duration': 3.0,
                        'parameters': {'bri': 50},
                        'target_type': 'all'
                    },
                    {
                        'type': 'transition',
                        'duration': 3.0,
                        'parameters': {'bri': 254},
                        'target_type': 'all'
                    },
                    {
                        'type': 'loop',
                        'duration': 0,
                        'parameters': {'count': -1},  # Endlos
                        'target_type': 'all'
                    }
                ],
                'preview_colors': ['#404040', '#FFFFFF']
            },
            'disco': {
                'name': 'Disco-Effekt',
                'description': 'Schnelle Farbwechsel mit zufälligen Farben',
                'steps': [
                    {
                        'type': 'color',
                        'duration': 0.5,
                        'parameters': {'hue': 'random', 'sat': 255, 'bri': 254},
                        'target_type': 'all'
                    },
                    {
                        'type': 'delay',
                        'duration': 0.2,
                        'parameters': {},
                        'target_type': 'all'
                    },
                    {
                        'type': 'loop',
                        'duration': 0,
                        'parameters': {'count': -1},
                        'target_type': 'all'
                    }
                ],
                'preview_colors': ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF']
            },
            'sunrise_custom': {
                'name': 'Sonnenaufgang',
                'description': 'Natürlicher Sonnenaufgang-Effekt',
                'steps': [
                    {
                        'type': 'color',
                        'duration': 0,
                        'parameters': {'hue': 8000, 'sat': 255, 'bri': 1},
                        'target_type': 'all'
                    },
                    {
                        'type': 'transition',
                        'duration': 300,  # 5 Minuten
                        'parameters': {'hue': 8000, 'sat': 200, 'bri': 200},
                        'target_type': 'all'
                    },
                    {
                        'type': 'transition',
                        'duration': 300,
                        'parameters': {'hue': 10000, 'sat': 150, 'bri': 254},
                        'target_type': 'all'
                    }
                ],
                'preview_colors': ['#FF4500', '#FFA500', '#FFFF99']
            }
        }
    
    def create_effect(self, name: str, description: str, category: str, author: str = 'user') -> CustomEffect:
        """Neuen Custom-Effekt erstellen"""
        effect = CustomEffect(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            category=category,
            author=author,
            created_at=datetime.now().isoformat(),
            steps=[],
            tags=[],
            preview_colors=['#FFFFFF']
        )
        return effect
    
    def add_step(self, effect: CustomEffect, step_type: str, duration: float, 
                 parameters: Dict[str, Any], target_type: str, target_id: str = None) -> EffectStep:
        """Schritt zu Effekt hinzufügen"""
        step = EffectStep(
            id=str(uuid.uuid4()),
            type=step_type,
            duration=duration,
            parameters=parameters,
            target_type=target_type,
            target_id=target_id
        )
        effect.steps.append(step)
        return step
    
    def remove_step(self, effect: CustomEffect, step_id: str) -> bool:
        """Schritt aus Effekt entfernen"""
        for i, step in enumerate(effect.steps):
            if step.id == step_id:
                effect.steps.pop(i)
                return True
        return False
    
    def reorder_steps(self, effect: CustomEffect, step_ids: List[str]) -> bool:
        """Schritte neu ordnen"""
        try:
            # Neue Reihenfolge erstellen
            new_steps = []
            for step_id in step_ids:
                for step in effect.steps:
                    if step.id == step_id:
                        new_steps.append(step)
                        break
            
            # Überprüfen ob alle Schritte gefunden wurden
            if len(new_steps) == len(effect.steps):
                effect.steps = new_steps
                return True
            return False
        except Exception:
            return False
    
    def validate_effect(self, effect: CustomEffect) -> Dict[str, Any]:
        """Effekt validieren"""
        issues = []
        warnings = []
        
        # Grundlegende Validierung
        if not effect.name or len(effect.name.strip()) < 3:
            issues.append("Name muss mindestens 3 Zeichen lang sein")
        
        if not effect.steps:
            issues.append("Effekt muss mindestens einen Schritt haben")
        
        # Schritt-Validierung
        has_loop = False
        for i, step in enumerate(effect.steps):
            if step.type == 'loop':
                has_loop = True
                if i != len(effect.steps) - 1:
                    warnings.append("Loop-Schritt sollte am Ende stehen")
            
            if step.duration < 0:
                issues.append(f"Schritt {i+1}: Dauer kann nicht negativ sein")
            
            if step.type == 'color':
                params = step.parameters
                if 'hue' in params and params['hue'] != 'random':
                    if not (0 <= params['hue'] <= 65535):
                        issues.append(f"Schritt {i+1}: Hue-Wert außerhalb gültigen Bereichs")
                if 'sat' in params and not (0 <= params['sat'] <= 255):
                    issues.append(f"Schritt {i+1}: Sättigung außerhalb gültigen Bereichs")
                if 'bri' in params and not (1 <= params['bri'] <= 254):
                    issues.append(f"Schritt {i+1}: Helligkeit außerhalb gültigen Bereichs")
        
        # Performance-Warnungen
        total_duration = sum(step.duration for step in effect.steps if step.type != 'loop')
        if total_duration > 3600:  # 1 Stunde
            warnings.append("Sehr langer Effekt - könnte Performance beeinträchtigen")
        
        if len(effect.steps) > 50:
            warnings.append("Sehr viele Schritte - könnte komplex werden")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'total_duration': total_duration,
            'has_loop': has_loop
        }
    
    def generate_preview_colors(self, effect: CustomEffect) -> List[str]:
        """Preview-Farben für Effekt generieren"""
        colors = []
        
        for step in effect.steps[:5]:  # Nur erste 5 Schritte
            if step.type in ['color', 'transition']:
                params = step.parameters
                if 'hue' in params and params['hue'] != 'random':
                    # Hue zu Hex konvertieren
                    hue = params['hue']
                    sat = params.get('sat', 255)
                    bri = params.get('bri', 254)
                    
                    # HSV zu RGB Konvertierung (vereinfacht)
                    h = hue / 65535 * 360
                    s = sat / 255
                    v = bri / 254
                    
                    import colorsys
                    r, g, b = colorsys.hsv_to_rgb(h/360, s, v)
                    hex_color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                    colors.append(hex_color)
        
        if not colors:
            colors = ['#FFFFFF']
        
        effect.preview_colors = colors[:8]  # Max 8 Preview-Farben
        return colors
    
    def save_effect(self, effect: CustomEffect) -> bool:
        """Effekt in Datenbank speichern"""
        if not self.db_pool:
            return self._save_to_file(effect)
        
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            
            # Vorherigen Effekt löschen falls vorhanden
            cursor.execute("DELETE FROM custom_effects WHERE id = %s", (effect.id,))
            
            # Neuen Effekt einfügen
            cursor.execute("""
                INSERT INTO custom_effects 
                (id, name, description, category, author, created_at, steps_json, 
                 tags_json, preview_colors_json, is_public)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                effect.id, effect.name, effect.description, effect.category,
                effect.author, effect.created_at,
                json.dumps([asdict(step) for step in effect.steps]),
                json.dumps(effect.tags),
                json.dumps(effect.preview_colors),
                effect.is_public
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Fehler beim Speichern: {e}")
            return False
    
    def _save_to_file(self, effect: CustomEffect) -> bool:
        """Fallback: Effekt in Datei speichern"""
        try:
            effects_dir = 'custom_effects'
            os.makedirs(effects_dir, exist_ok=True)
            
            filename = f"{effects_dir}/{effect.id}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(asdict(effect), f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False
    
    def load_effect(self, effect_id: str) -> Optional[CustomEffect]:
        """Effekt laden"""
        if not self.db_pool:
            return self._load_from_file(effect_id)
        
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM custom_effects WHERE id = %s", (effect_id,))
            row = cursor.fetchone()
            
            if row:
                steps_data = json.loads(row[6])  # steps_json
                steps = [EffectStep(**step_data) for step_data in steps_data]
                
                effect = CustomEffect(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    category=row[3],
                    author=row[4],
                    created_at=row[5],
                    steps=steps,
                    tags=json.loads(row[7]),  # tags_json
                    preview_colors=json.loads(row[8]),  # preview_colors_json
                    is_public=row[9]
                )
                return effect
            
            conn.close()
            return None
            
        except Exception as e:
            print(f"Fehler beim Laden: {e}")
            return None
    
    def _load_from_file(self, effect_id: str) -> Optional[CustomEffect]:
        """Fallback: Effekt aus Datei laden"""
        try:
            filename = f"custom_effects/{effect_id}.json"
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                steps = [EffectStep(**step_data) for step_data in data['steps']]
                data['steps'] = steps
                return CustomEffect(**data)
            return None
        except Exception:
            return None
    
    def list_effects(self, category: str = None, author: str = None) -> List[Dict[str, Any]]:
        """Alle Effekte auflisten"""
        effects = []
        
        if not self.db_pool:
            return self._list_from_files(category, author)
        
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            
            query = "SELECT id, name, description, category, author, created_at, preview_colors_json FROM custom_effects"
            params = []
            
            conditions = []
            if category:
                conditions.append("category = %s")
                params.append(category)
            if author:
                conditions.append("author = %s")
                params.append(author)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                effects.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'category': row[3],
                    'author': row[4],
                    'created_at': row[5],
                    'preview_colors': json.loads(row[6])
                })
            
            conn.close()
            return effects
            
        except Exception as e:
            print(f"Fehler beim Auflisten: {e}")
            return []
    
    def _list_from_files(self, category: str = None, author: str = None) -> List[Dict[str, Any]]:
        """Fallback: Effekte aus Dateien auflisten"""
        effects = []
        effects_dir = 'custom_effects'
        
        if not os.path.exists(effects_dir):
            return effects
        
        for filename in os.listdir(effects_dir):
            if filename.endswith('.json'):
                try:
                    with open(f"{effects_dir}/{filename}", 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if category and data.get('category') != category:
                        continue
                    if author and data.get('author') != author:
                        continue
                    
                    effects.append({
                        'id': data['id'],
                        'name': data['name'],
                        'description': data['description'],
                        'category': data['category'],
                        'author': data['author'],
                        'created_at': data['created_at'],
                        'preview_colors': data.get('preview_colors', ['#FFFFFF'])
                    })
                except Exception:
                    continue
        
        return sorted(effects, key=lambda x: x['created_at'], reverse=True)
    
    def delete_effect(self, effect_id: str) -> bool:
        """Effekt löschen"""
        if not self.db_pool:
            return self._delete_file(effect_id)
        
        try:
            conn = self.db_pool.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM custom_effects WHERE id = %s", (effect_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            return deleted
            
        except Exception:
            return False
    
    def _delete_file(self, effect_id: str) -> bool:
        """Fallback: Effekt-Datei löschen"""
        try:
            filename = f"custom_effects/{effect_id}.json"
            if os.path.exists(filename):
                os.remove(filename)
                return True
            return False
        except Exception:
            return False
    
    def get_templates(self) -> Dict[str, Any]:
        """Verfügbare Templates zurückgeben"""
        return self.predefined_templates
    
    def create_from_template(self, template_key: str, name: str, author: str = 'user') -> Optional[CustomEffect]:
        """Effekt aus Template erstellen"""
        if template_key not in self.predefined_templates:
            return None
        
        template = self.predefined_templates[template_key]
        effect = self.create_effect(
            name=name,
            description=template['description'],
            category='template',
            author=author
        )
        
        # Schritte aus Template übernehmen
        for step_data in template['steps']:
            self.add_step(
                effect=effect,
                step_type=step_data['type'],
                duration=step_data['duration'],
                parameters=step_data['parameters'],
                target_type=step_data['target_type'],
                target_id=step_data.get('target_id')
            )
        
        effect.preview_colors = template['preview_colors']
        return effect

# Utility-Funktionen für die Integration
def init_effect_builder_db(db_pool):
    """Datenbank-Tabelle für Custom-Effekte erstellen"""
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_effects (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                category VARCHAR(50) NOT NULL,
                author VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL,
                steps_json TEXT NOT NULL,
                tags_json TEXT,
                preview_colors_json TEXT,
                is_public BOOLEAN DEFAULT FALSE,
                INDEX idx_category (category),
                INDEX idx_author (author),
                INDEX idx_created (created_at)
            )
        """)
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Fehler beim Erstellen der Custom-Effects Tabelle: {e}")
        return False

# Beispiel-Verwendung
if __name__ == "__main__":
    builder = EffectBuilder()
    
    # Neuen Effekt erstellen
    effect = builder.create_effect(
        name="Mein Regenbogen",
        description="Sanfter Regenbogen-Effekt",
        category="custom",
        author="testuser"
    )
    
    # Schritte hinzufügen
    builder.add_step(effect, 'color', 2.0, {'hue': 0, 'sat': 255, 'bri': 200}, 'all')
    builder.add_step(effect, 'transition', 2.0, {'hue': 15000, 'sat': 255, 'bri': 200}, 'all')
    builder.add_step(effect, 'transition', 2.0, {'hue': 30000, 'sat': 255, 'bri': 200}, 'all')
    builder.add_step(effect, 'loop', 0, {'count': -1}, 'all')
    
    # Validierung
    validation = builder.validate_effect(effect)
    print(f"Validation: {validation}")
    
    # Preview-Farben generieren
    colors = builder.generate_preview_colors(effect)
    print(f"Preview Colors: {colors}")
    
    # Speichern
    success = builder.save_effect(effect)
    print(f"Saved: {success}")