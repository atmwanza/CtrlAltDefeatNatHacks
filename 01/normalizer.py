import csv

x = []
y = []
pressure = []
grip_angle = []
timestamp = []

with open('data.txt', mode='r', newline='', encoding='utf-8') as file:
    reader = csv.reader(file, delimiter=';')
    for row in reader:
        if not row or row[6] != '0':  # skip blank lines and non-static tests
            continue
        x.append(float(row[0]))
        y.append(float(row[1]))
        pressure.append(float(row[3]))
        grip_angle.append(float(row[4]))
        timestamp.append(float(row[5]))

# normalize each drawing by its own mean (ignoring pen-up zeros)
nonzero_p = [p for p in pressure if p > 0]
mean_p = sum(nonzero_p) / len(nonzero_p)
pressure_norm = [p / mean_p for p in pressure]

mean_g = sum(grip_angle) / len(grip_angle)
grip_angle_norm = [g / mean_g for g in grip_angle]