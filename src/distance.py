def cosine_distance(u, v):
    return 1.0 - (np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))

