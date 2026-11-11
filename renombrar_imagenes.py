import os

carpeta = "static/img"
for f in os.listdir(carpeta):
    nuevo = f.lower().replace(" ", "-")
    if nuevo != f:
        os.rename(os.path.join(carpeta, f), os.path.join(carpeta, nuevo))
        print(f, "->", nuevo)