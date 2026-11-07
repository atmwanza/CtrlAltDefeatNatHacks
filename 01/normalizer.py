import csv


def load_spiral(path):
    data = {'x': [], 'y': [], 'pressure': [], 'grip_angle': [], 'timestamp': []}
    with open(path, mode='r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if not row or row[6] != '0':
                continue
            data['x'].append(float(row[0]))
            data['y'].append(float(row[1]))
            data['pressure'].append(float(row[3]))
            data['grip_angle'].append(float(row[4]))
            data['timestamp'].append(float(row[5]))
    return data


def normalize(signal):
    nonzero = [v for v in signal if v > 0]
    mean = sum(nonzero) / len(nonzero)
    return [v / mean for v in signal]