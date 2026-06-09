from ultralytics import YOLO

# 1. Load the model
# By specifying 'yolov8x-obb.pt', the library will automatically 
# reach out to the Ultralytics servers, download the DOTA pre-trained 
# weights, and load them into memory. 
# (The 'x' stands for extra-large, which is the most accurate version).
model = YOLO('yolov8x-obb.pt')

# 2. Run the model on your folder of screenshots
# The 'save=True' argument tells the model to draw the bounding boxes 
# on the images and save them in a new folder so you can see the results.
results = model(source='my_images/', save=True)

# 3. Extract the coordinates (Optional: if you want to see the raw data)
for r in results:
    # r.obb contains the oriented bounding box data for that image
    if r.obb is not None:
        print(f"Found {len(r.obb)} objects in this image.")
        # Print the normalized coordinates of the 4 corners of each box
        print(r.obb.xyxyxyxy)