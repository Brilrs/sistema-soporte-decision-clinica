// Pantallas que se construyen en los siguientes Sprints.
export default function EnConstruccion({ titulo, pantalla, sprint }: { titulo: string; pantalla: string; sprint: number }) {
  return (
    <section>
      <h1>{titulo}</h1>
      <div className="tarjeta tarjeta--vacia">
        <p><strong>{pantalla}</strong> se desarrolla en el Sprint {sprint}.</p>
      </div>
    </section>
  );
}
