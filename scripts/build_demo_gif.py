import os

from PIL import Image, ImageDraw, ImageFont

FRAMES_DIR = os.path.join(os.path.dirname(__file__), "../docs/images/demo_frames")
OUTPUT_GIF = os.path.join(os.path.dirname(__file__), "../docs/images/demo.gif")

FRAME_CAPTIONS = {
    "01_overview.png": "1/11 Overview: Distributed Transaction Metrics & Queue Backlog",
    "02_place_order_form.png": "2/11 Place Order: Clean Form with Fault Simulation Support",
    "03_happy_path_completed.png": "3/11 Happy Path: All Steps Complete (Inventory -> Payment -> Shipping)",
    "04_shipping_fail_selected.png": "4/11 Fault Injection: Simulating Downstream Shipping Failure",
    "05_shipping_failed_compensating.png": "5/11 Step Failure: Shipping Fails (NO_CARRIER_AVAILABLE)",
    "06_compensation_completed.png": "6/11 Auto-Compensation: Reverse Order (Payment Voided, Inventory Freed)",
    "07_attn_scenario_selected.png": "7/11 Complex Fault: Shipping Failure + Payment-Void Failure",
    "08_requires_attention_state.png": "8/11 REQUIRES_ATTENTION: Halt on Compensation Failure (No Blind Undo)",
    "09_failed_workflows_view.png": "9/11 Operator Dashboard: Quarantine View with Safe Recovery Controls",
    "10_recovered_compensated.png": "10/11 Manual Retry: Fault Cleared -> Resumes and Fully Compensates",
    "11_system_health.png": "11/11 System Health: All Microservices Up, Ready, and Monitored",
}

def add_banner(img: Image.Image, text: str) -> Image.Image:
    # Resize slightly for crisp 1024 width GIF
    target_width = 1024
    w, h = img.size
    target_height = int(h * (target_width / w))
    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Add top banner
    banner_height = 42
    new_img = Image.new("RGB", (target_width, target_height + banner_height), (15, 23, 42)) # slate-900
    new_img.paste(img, (0, banner_height))
    
    draw = ImageDraw.Draw(new_img)
    # Default PIL bitmap font
    font = ImageFont.load_default()
    
    # Draw dark pill background for text
    draw.rectangle([0, 0, target_width, banner_height], fill=(15, 23, 42))
    draw.text((20, 14), text, fill=(255, 255, 255), font=font)
    
    return new_img

def main():
    frame_files = sorted(os.listdir(FRAMES_DIR))
    images = []
    durations = []
    
    for fname in frame_files:
        if not fname.endswith(".png"):
            continue
        fpath = os.path.join(FRAMES_DIR, fname)
        im = Image.open(fpath).convert("RGB")
        caption = FRAME_CAPTIONS.get(fname, fname)
        framed = add_banner(im, caption)
        # Convert to P mode with adaptive palette for clean GIF compression
        images.append(framed.convert("P", palette=Image.Palette.ADAPTIVE))
        durations.append(4000) # 4 seconds per frame
        print(f"Processed frame: {fname}")
        
    if images:
        images[0].save(
            OUTPUT_GIF,
            save_all=True,
            append_images=images[1:],
            optimize=True,
            duration=durations,
            loop=0
        )
        print(f"Saved animated demo GIF: {OUTPUT_GIF} ({os.path.getsize(OUTPUT_GIF)} bytes)")

if __name__ == "__main__":
    main()
