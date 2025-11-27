# Thorlabs KDC101 Driver

Cette documentation décrit l'implémentation du driver Thorlabs KDC101 pour le contrôleur moteur DC dans le projet MicroPL.

## Description

Le KDC101 est un contrôleur moteur DC compact de Thorlabs, utilisé dans ce projet pour:
- Contrôler un polariseur motorisé (PRM1-Z8)
- Gérer une sortie TTL pour contrôler un shutter

## Prérequis

### Matériel
- KDC101 DC Motor Controller
- Monture de rotation motorisée (ex: PRM1-Z8)
- Connexion USB vers l'ordinateur

### Logiciel
- **Windows OS** (obligatoire)
- **Thorlabs Kinesis Software** installé
  - Téléchargez depuis: https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control
  - Installez dans le chemin par défaut: `C:\Program Files\Thorlabs\Kinesis`
- Python 3.9+

## Architecture

Le driver est implémenté dans `/src/micropl/hardware/kdc101.py` et utilise:
- **ctypes** pour interfacer avec la DLL Kinesis C API
- **Architecture abstraite** héritée de `MotorizedDevice`
- **Conversions d'unités** automatiques (unités réelles ↔ unités device)

## Fonctionnalités implémentées

### Connexion et initialisation
- ✅ `connect()` - Connexion au contrôleur
- ✅ `disconnect()` - Déconnexion propre
- ✅ `is_connected()` - Vérification du statut
- ✅ `get_info()` - Informations sur le device

### Mouvements
- ✅ `home()` - Homing du moteur (avec timeout et vérification)
- ✅ `move_to(position)` - Mouvement absolu en unités réelles (degrés)
- ✅ `move_by(delta)` - Mouvement relatif
- ✅ `get_position()` - Lecture de la position actuelle
- ✅ `wait_for_move(timeout)` - Attente de fin de mouvement
- ✅ `stop()` - Arrêt immédiat du mouvement

### Contrôle TTL
- ✅ `set_ttl_output(state)` - Contrôle de la sortie TTL (HIGH/LOW)

### Autres
- ✅ Support du context manager (`with` statement)
- ✅ Gestion des erreurs avec logging détaillé
- ⚠️ `set_velocity()` - Partiellement implémenté (nécessite structure de paramètres complète)

## Configuration

### Dans `default.yaml`

```yaml
hardware:
  kdc101:
    serial_number: "27500125"  # Votre numéro de série
    kinesis_path: "C:\\Program Files\\Thorlabs\\Kinesis"
    steps_per_rev: 1919.64186  # Pour PRM1-Z8
    gbox_ratio: 1.0
    pitch: 1.0
    velocity: 10.0
    acceleration: 10.0
```

### Trouver le numéro de série

Utilisez Kinesis software ou vérifiez l'étiquette sur le KDC101.

## Exemples d'utilisation

### Exemple basique

```python
from micropl.hardware.factory import create_instrument

config = {
    'serial_number': '27500125',
}

kdc = create_instrument('kdc101', config)
kdc.connect()

try:
    # Home the device
    kdc.home()

    # Move to position
    kdc.move_to(45.0)  # 45 degrés
    kdc.wait_for_move()

    # Read position
    position = kdc.get_position()
    print(f"Position: {position:.2f}°")

finally:
    kdc.disconnect()
```

### Avec context manager (recommandé)

```python
with create_instrument('kdc101', config) as kdc:
    kdc.home()
    kdc.move_to(90.0)
    kdc.wait_for_move()
    # Déconnexion automatique
```

### Contrôle du shutter

```python
kdc = create_instrument('kdc101', config)
kdc.connect()

# Ouvrir le shutter
kdc.set_ttl_output(True)

# ... acquisition de données ...

# Fermer le shutter
kdc.set_ttl_output(False)

kdc.disconnect()
```

### Balayage de polarisation

```python
with create_instrument('kdc101', config) as kdc:
    kdc.home()

    # Balayer de 0 à 180° par pas de 15°
    for angle in range(0, 181, 15):
        kdc.move_to(float(angle))
        kdc.wait_for_move()

        # Acquérir des données à cette position
        # ...
```

Plus d'exemples dans `example_kdc101_usage.py`.

## API Kinesis utilisée

Le driver utilise les fonctions suivantes de la DLL `Thorlabs.MotionControl.KCube.DCServo.dll`:

| Fonction | Usage |
|----------|-------|
| `TLI_BuildDeviceList()` | Énumération des devices |
| `CC_Open()` | Ouverture de la connexion |
| `CC_Close()` | Fermeture de la connexion |
| `CC_StartPolling()` | Démarrage du polling |
| `CC_StopPolling()` | Arrêt du polling |
| `CC_Home()` | Homing du moteur |
| `CC_SetMotorParamsExt()` | Configuration des paramètres moteur |
| `CC_MoveAbsolute()` | Mouvement absolu |
| `CC_SetMoveAbsolutePosition()` | Définir la position cible |
| `CC_GetPosition()` | Lire la position |
| `CC_RequestPosition()` | Demander mise à jour position |
| `CC_GetDeviceUnitFromRealValue()` | Conversion real → device |
| `CC_GetRealValueFromDeviceUnit()` | Conversion device → real |
| `CC_GetStatusBits()` | Lire le statut |
| `CC_RequestStatusBits()` | Demander mise à jour statut |
| `CC_SetDigitalOutputs()` | Contrôle sortie TTL |
| `CC_StopImmediate()` | Arrêt immédiat |

## Paramètres moteur

Les paramètres par défaut sont configurés pour la monture **PRM1-Z8**:

- **Steps per revolution**: 1919.64186
- **Gearbox ratio**: 1.0
- **Pitch**: 1.0

Pour d'autres montures, consultez la documentation Thorlabs et ajustez ces paramètres dans la configuration.

## Dépannage

### "Could not load Kinesis DLL"
- Vérifiez que Kinesis est installé
- Vérifiez le chemin dans `kinesis_path`
- Redémarrez Python après l'installation

### "TLI_BuildDeviceList failed"
- Vérifiez que le KDC101 est connecté via USB
- Vérifiez dans Kinesis que le device est détecté
- Essayez de déconnecter/reconnecter le USB

### "CC_Open failed"
- Vérifiez le numéro de série dans la configuration
- Fermez Kinesis s'il est ouvert (conflit d'accès)
- Le device peut être déjà ouvert par un autre processus

### Le mouvement ne se termine pas
- Augmentez le timeout dans `wait_for_move()`
- Vérifiez que le moteur n'est pas bloqué mécaniquement
- Vérifiez l'alimentation du KDC101

### Position incorrecte
- Vérifiez les paramètres `steps_per_rev`, `gbox_ratio`, `pitch`
- Home le device avant utilisation
- Consultez la documentation de votre monture

## Limitations connues

1. **set_velocity()** n'est pas complètement implémenté
   - Nécessite la structure complète des paramètres de vélocité
   - Sera implémenté dans une version future

2. **Windows uniquement**
   - La DLL Kinesis n'est disponible que sur Windows
   - Pour macOS/Linux, utiliser d'autres solutions (pylablib, thorlabs_apt)

3. **Pas de support simulations**
   - Le code pour `TLI_InitializeSimulations()` est commenté
   - Décommentez si vous voulez tester sans hardware

## Références

- [Thorlabs KDC101 Product Page](https://www.thorlabs.com/thorproduct.cfm?partnumber=KDC101)
- [Kinesis Software Download](https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control)
- [Kinesis C API Documentation](https://www.thorlabs.com/software/apt/APT_Communications_Protocol_Rev_15.pdf)

## Auteur

Implémenté pour le projet MicroPL basé sur l'exemple Thorlabs.
