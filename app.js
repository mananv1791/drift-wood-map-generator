const controls = {
  outputWidth: byId("outputWidth"),
  outputHeight: byId("outputHeight"),
  boardSizePreset: byId("boardSizePreset"),
  tilesX: byId("tilesX"),
  tilesY: byId("tilesY"),
  riverPlacement: byId("riverPlacement"),
  planetTheme: byId("planetTheme"),
  scale: byId("scale"),
  offsetX: byId("offsetX"),
  offsetY: byId("offsetY"),
  relief: byId("relief"),
  height: byId("height"),
  maxHeight: byId("maxHeight"),
  minHeight: byId("minHeight"),
  terrainPreset: byId("terrainPreset"),
  countWater: byId("countWater"),
  countSand: byId("countSand"),
  countPlain: byId("countPlain"),
  countForest: byId("countForest"),
  countStone: byId("countStone"),
  countMountain: byId("countMountain"),
  featureVillage: byId("featureVillage"),
  featureForest: byId("featureForest"),
  featureReefs: byId("featureReefs"),
  featureBoar: byId("featureBoar"),
  featureFrozenWater: byId("featureFrozenWater"),
  featureMountainErosion: byId("featureMountainErosion"),
  colorSand: byId("colorSand"),
  colorPlain: byId("colorPlain"),
  colorForest: byId("colorForest"),
  colorDeepForest: byId("colorDeepForest"),
  colorStone: byId("colorStone"),
  colorRock: byId("colorRock"),
  colorDeepWater: byId("colorDeepWater"),
  colorFoam: byId("colorFoam"),
  waterAspect: byId("waterAspect"),
  reefAmount: byId("reefAmount"),
  reefSize: byId("reefSize"),
  generateBtn: byId("generateBtn"),
  randomizeBtn: byId("randomizeBtn"),
};

const mapImage = byId("mapImage");
const previewStatus = byId("previewStatus");
const countSummary = byId("countSummary");

let currentSeed = Math.floor(Math.random() * 1e9);
let currentUrl = null;

const boardSizePresets = {
  "12x10": { x: 12, y: 10 },
  "16x12": { x: 16, y: 12 },
  "18x14": { x: 18, y: 14 },
  "20x16": { x: 20, y: 16 },
  "24x18": { x: 24, y: 18 },
};

const terrainMixes = {
  balanced: { water: 0.22, sand: 0.12, plain: 0.31, forest: 0.17, stone: 0.11, mountain: 0.07 },
  riverlands: { water: 0.27, sand: 0.14, plain: 0.28, forest: 0.16, stone: 0.09, mountain: 0.06 },
  archipelago: { water: 0.36, sand: 0.16, plain: 0.2, forest: 0.12, stone: 0.09, mountain: 0.07 },
  highlands: { water: 0.16, sand: 0.08, plain: 0.24, forest: 0.18, stone: 0.18, mountain: 0.16 },
  woodlands: { water: 0.18, sand: 0.09, plain: 0.22, forest: 0.31, stone: 0.12, mountain: 0.08 },
};

const planetPalettes = {
  earth: {
    sand: "#dfca72",
    plain: "#6fca49",
    forest: "#399326",
    deepForest: "#214f17",
    stone: "#718176",
    rock: "#a5b3af",
    deepWater: "#235f95",
    foam: "#cdeef7",
  },
  desert: {
    sand: "#d8b36a",
    plain: "#c7954c",
    forest: "#6b8a3a",
    deepForest: "#496227",
    stone: "#8d7763",
    rock: "#c4ab8f",
    deepWater: "#2a7f8a",
    foam: "#d8f1ea",
  },
  frozen: {
    sand: "#c9d3dd",
    plain: "#d9e7ee",
    forest: "#7bb7c8",
    deepForest: "#4a7a8b",
    stone: "#8fa2b7",
    rock: "#e6eef7",
    deepWater: "#4e7db5",
    foam: "#f3fbff",
  },
  volcanic: {
    sand: "#6b4a36",
    plain: "#594136",
    forest: "#6f5b44",
    deepForest: "#45352f",
    stone: "#5b5a60",
    rock: "#8f8b94",
    deepWater: "#2f4158",
    foam: "#f1a36b",
  },
  alien: {
    sand: "#a7d36a",
    plain: "#4ecb8b",
    forest: "#16916a",
    deepForest: "#0d5a4e",
    stone: "#6e78c8",
    rock: "#b6a8ff",
    deepWater: "#1e5f8e",
    foam: "#b8fff0",
  },
};

for (const control of Object.values(controls)) {
  if (control instanceof HTMLInputElement && control.type !== "button") {
    control.addEventListener("input", syncNumericBounds);
    control.addEventListener("change", syncNumericBounds);
  }
}

controls.boardSizePreset.addEventListener("change", applyBoardSizePreset);
controls.terrainPreset.addEventListener("change", applyTerrainPreset);
controls.planetTheme.addEventListener("change", applyPlanetTheme);
controls.tilesX.addEventListener("change", syncPresetFromBoardSize);
controls.tilesY.addEventListener("change", syncPresetFromBoardSize);

for (const control of terrainCountInputs()) {
  control.addEventListener("input", () => {
    controls.terrainPreset.value = "custom";
    updateTerrainSummary();
  });
}

controls.generateBtn.addEventListener("click", generateMap);
controls.randomizeBtn.addEventListener("click", () => {
  currentSeed = Math.floor(Math.random() * 1e9);
  generateMap();
});

setStatus('Waiting to generate. Start the local server with "python3 server.py", then click Generate Map.');
applyPlanetTheme();
syncPresetFromBoardSize();
updateTerrainSummary();

async function generateMap() {
  const settings = readSettings();
  if (!hasValidTerrainCounts(settings)) {
    setStatus(
      `Terrain counts must add up to ${settings.tilesX * settings.tilesY} tiles before generating.`,
      "error"
    );
    return;
  }

  setStatus("Generating map...", "loading");

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `Request failed with ${response.status}`);
    }

    const blob = await response.blob();
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = URL.createObjectURL(blob);
    mapImage.src = currentUrl;
    setStatus(`Generated seed ${currentSeed}. Change settings and click Generate Map again.`);
  } catch (error) {
    setStatus(
      `Generation failed. Run this app through the local server with "python3 server.py". ${error instanceof Error ? error.message : String(error)}`,
      "error"
    );
    console.error(error);
  }
}

function readSettings() {
  return {
    seed: currentSeed,
    outputWidth: clamp(number(controls.outputWidth), 640, 4096),
    outputHeight: clamp(number(controls.outputHeight), 480, 4096),
    tilesX: clamp(Math.round(number(controls.tilesX)), 4, 120),
    tilesY: clamp(Math.round(number(controls.tilesY)), 4, 120),
    riverPlacement: controls.riverPlacement.value,
    planetTheme: controls.planetTheme.value,
    scale: clamp(number(controls.scale), 0.2, 2),
    offsetX: clamp(number(controls.offsetX), -1, 1),
    offsetY: clamp(number(controls.offsetY), -1, 1),
    relief: clamp(number(controls.relief), 0, 1),
    height: clamp(number(controls.height), 0.15, 1.2),
    maxHeight: clamp(number(controls.maxHeight), 0.35, 1.3),
    minHeight: clamp(number(controls.minHeight), 0, 0.6),
    terrainCounts: {
      water: clampInt(controls.countWater, 0, 100000),
      sand: clampInt(controls.countSand, 0, 100000),
      plain: clampInt(controls.countPlain, 0, 100000),
      forest: clampInt(controls.countForest, 0, 100000),
      stone: clampInt(controls.countStone, 0, 100000),
      mountain: clampInt(controls.countMountain, 0, 100000),
    },
    features: {
      village: controls.featureVillage.checked,
      forest: controls.featureForest.checked,
      reefs: controls.featureReefs.checked,
      boar: controls.featureBoar.checked,
      frozenWater: controls.featureFrozenWater.checked,
      erosion: controls.featureMountainErosion.checked,
    },
    colors: {
      sand: controls.colorSand.value,
      plain: controls.colorPlain.value,
      forest: controls.colorForest.value,
      deepForest: controls.colorDeepForest.value,
      stone: controls.colorStone.value,
      rock: controls.colorRock.value,
      deepWater: controls.colorDeepWater.value,
      foam: controls.colorFoam.value,
    },
    waterAspect: clamp(number(controls.waterAspect), 0.5, 1),
    reefAmount: clamp(number(controls.reefAmount), 0, 1),
    reefSize: clamp(number(controls.reefSize), 0.2, 1),
  };
}

function setStatus(message, state = "idle") {
  previewStatus.textContent = message;
  previewStatus.dataset.state = state;
}

function syncNumericBounds(event) {
  const input = event.currentTarget;
  if (!(input instanceof HTMLInputElement) || input.type !== "number") return;

  const min = input.min === "" ? Number.NEGATIVE_INFINITY : Number(input.min);
  const max = input.max === "" ? Number.POSITIVE_INFINITY : Number(input.max);
  const value = Number(input.value);
  if (!Number.isNaN(value)) input.value = String(clamp(value, min, max));
  updateTerrainSummary();
}

function applyBoardSizePreset() {
  const preset = boardSizePresets[controls.boardSizePreset.value];
  if (!preset) return;
  controls.tilesX.value = String(preset.x);
  controls.tilesY.value = String(preset.y);
  if (controls.terrainPreset.value !== "custom") {
    applyTerrainPreset();
  } else {
    updateTerrainSummary();
  }
}

function syncPresetFromBoardSize() {
  const match = Object.entries(boardSizePresets).find(([, preset]) => (
    preset.x === clampInt(controls.tilesX, 4, 120) &&
    preset.y === clampInt(controls.tilesY, 4, 120)
  ));
  controls.boardSizePreset.value = match ? match[0] : "custom";
  updateTerrainSummary();
}

function applyTerrainPreset() {
  const preset = terrainMixes[controls.terrainPreset.value];
  if (!preset) {
    updateTerrainSummary();
    return;
  }

  const totalTiles = clampInt(controls.tilesX, 4, 120) * clampInt(controls.tilesY, 4, 120);
  const keys = ["water", "sand", "plain", "forest", "stone", "mountain"];
  const values = {};
  let assigned = 0;

  for (const key of keys) {
    const value = Math.floor(totalTiles * preset[key]);
    values[key] = value;
    assigned += value;
  }

  const remainders = keys
    .map((key) => ({ key, remainder: totalTiles * preset[key] - values[key] }))
    .sort((a, b) => b.remainder - a.remainder);

  for (let i = 0; i < totalTiles - assigned; i += 1) {
    values[remainders[i % remainders.length].key] += 1;
  }

  controls.countWater.value = String(values.water);
  controls.countSand.value = String(values.sand);
  controls.countPlain.value = String(values.plain);
  controls.countForest.value = String(values.forest);
  controls.countStone.value = String(values.stone);
  controls.countMountain.value = String(values.mountain);
  updateTerrainSummary();
}

function applyPlanetTheme() {
  const palette = planetPalettes[controls.planetTheme.value];
  if (!palette) return;
  controls.colorSand.value = palette.sand;
  controls.colorPlain.value = palette.plain;
  controls.colorForest.value = palette.forest;
  controls.colorDeepForest.value = palette.deepForest;
  controls.colorStone.value = palette.stone;
  controls.colorRock.value = palette.rock;
  controls.colorDeepWater.value = palette.deepWater;
  controls.colorFoam.value = palette.foam;
}

function updateTerrainSummary() {
  const settings = readSettings();
  const required = settings.tilesX * settings.tilesY;
  const total = sumTerrainCounts(settings.terrainCounts);
  const valid = total === required;

  countSummary.textContent = `Terrain total ${total} / ${required} tiles`;
  countSummary.dataset.state = valid ? "valid" : "invalid";
  controls.generateBtn.disabled = !valid;
}

function hasValidTerrainCounts(settings) {
  return sumTerrainCounts(settings.terrainCounts) === settings.tilesX * settings.tilesY;
}

function sumTerrainCounts(counts) {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}

function clampInt(el, min, max) {
  return clamp(Math.round(number(el)), min, max);
}

function terrainCountInputs() {
  return [
    controls.countWater,
    controls.countSand,
    controls.countPlain,
    controls.countForest,
    controls.countStone,
    controls.countMountain,
  ];
}

function byId(id) {
  return document.getElementById(id);
}

function number(el) {
  return Number(el.value);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
