/**
 * Deterministic property imagery from Unsplash source.
 * Given a seed (building name/id), returns the same image every time.
 */
const PROPERTY_IMAGES = [
  "photo-1570129477492-45c003edd2be", // modern apartment
  "photo-1512917774080-9991f1c4c750", // villa
  "photo-1568605114967-8130f3a36994", // townhouse
  "photo-1600585154340-be6161a56a0c", // contemporary home
  "photo-1564013799919-ab600027ffc6", // cozy interior-ext
  "photo-1600596542815-ffad4c1539a9", // brick facade
  "photo-1600607687939-ce8a6c25118c", // airy interior
  "photo-1613553474179-e1eda3ea5734", // apartment block
  "photo-1580587771525-78b9dba3b914", // glass facade
  "photo-1512917774080-9991f1c4c750", // stone villa
  "photo-1582268611958-ebfd161ef9cf", // urban apartments
  "photo-1486406146926-c627a92ad1ab", // residential row
];

function hash(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export function propertyImage(seed: string | number, size: "sm" | "md" | "lg" = "md") {
  const w = size === "sm" ? 400 : size === "md" ? 800 : 1400;
  const id = PROPERTY_IMAGES[hash(String(seed)) % PROPERTY_IMAGES.length];
  return `https://images.unsplash.com/${id}?auto=format&fit=crop&q=80&w=${w}`;
}

export function avatarFor(seed: string | number) {
  // Solid gold/brown backgrounds — no gradient. Dicebear picks one per seed.
  return `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(
    String(seed)
  )}&backgroundType=solid&backgroundColor=C6A75E,A68A4A,2C1F1A,5C3E2A&fontSize=42`;
}
