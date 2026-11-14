// Allocate from the full schedule, never the filtered view. Sorted IDs keep
// colours stable after reloads and independent of response ordering.
const hues = [153, 210, 35, 275, 355, 180, 65, 310, 125, 235, 20, 290, 165, 195, 50, 255, 335, 95, 140, 225];
export function moduleColours(ids) {
  return new Map([...new Set(ids)].sort().map((id, index) => {
    const hue = hues[index] ?? (index * 137.508) % 360;
    return [id, `--module-colour:hsl(${hue} 48% 76%);--module-wash:hsl(${hue} 22% 18%);--module-hover:hsl(${hue} 24% 23%)`];
  }));
}
